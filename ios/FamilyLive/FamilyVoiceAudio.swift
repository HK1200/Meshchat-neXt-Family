import AVFoundation
import Foundation
import UIKit

@MainActor
final class FamilyVoiceAudio {
    private var engine = AVAudioEngine()
    private var player = AVAudioPlayerNode()
    private var pump: VoicePCMPump?
    private var tapInstalled = false
    private var sessionActive = false
    private var managedAudio = false
    private var nativeCaptureStarted: ContinuousClock.Instant?
    private(set) var callID: String?

    init() { engine.attach(player) }

    var usingBuiltInSpeaker: Bool {
        AVAudioSession.sharedInstance().currentRoute.outputs.contains { $0.portType == .builtInSpeaker }
    }

    func start(callID: String, managedAudio: Bool = false) throws {
        guard self.callID != callID else { return }
        stop()
        do {
            try start(callID: callID, useVoiceProcessing: true, managedAudio: managedAudio)
        } catch {
            try start(callID: callID, useVoiceProcessing: false, managedAudio: managedAudio)
        }
    }

    private func start(callID: String, useVoiceProcessing: Bool, managedAudio: Bool) throws {
        self.managedAudio = managedAudio
        let session = AVAudioSession.sharedInstance()
        do {
            try FamilyCallAudioSession.configure()
            try session.setPreferredSampleRate(48_000)
            try session.setPreferredIOBufferDuration(0.02)
            if !managedAudio { try session.setActive(true) }
            sessionActive = !managedAudio

            let input = engine.inputNode
            if input.isVoiceProcessingEnabled != useVoiceProcessing {
                try input.setVoiceProcessingEnabled(useVoiceProcessing)
            }
            let hardware = input.outputFormat(forBus: 0)
            guard hardware.sampleRate > 0, hardware.channelCount > 0,
                  let playback = AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 1) else {
                throw AudioError.unavailable
            }
            engine.connect(player, to: engine.mainMixerNode, format: playback)
            let pump = VoicePCMPump(callID: callID, player: player, format: playback,
                                    nativeProcessing: input.isVoiceProcessingEnabled)
            let capture = try VoiceMicrophoneCapture(input: hardware, output: playback, pump: pump)
            self.pump = pump
            input.installTap(onBus: 0, bufferSize: 960, format: hardware) { buffer, _ in
                capture.receive(buffer)
            }
            tapInstalled = true
            engine.prepare()
            try engine.start()
            player.play()
            pump.start()
            self.callID = callID
            nativeCaptureStarted = input.isVoiceProcessingEnabled ? ContinuousClock.now : nil
        } catch {
            stop()
            throw error
        }
    }

    var captureStatus: String {
        pump?.captureStatus ?? "Starting microphone"
    }

    var playbackHealth: [String: Any] { pump?.playbackHealth ?? [:] }

    func recoverStalledCapture() throws {
        guard let started = nativeCaptureStarted, let callID, let pump else { return }
        if pump.hasCapturedPCM {
            nativeCaptureStarted = nil
            return
        }
        guard started.duration(to: ContinuousClock.now) >= .seconds(2) else { return }
        let managed = managedAudio
        stop()
        try start(callID: callID, useVoiceProcessing: false, managedAudio: managed)
    }

    func setSpeaker(_ enabled: Bool) throws {
        guard callID != nil else { return }
        try AVAudioSession.sharedInstance().overrideOutputAudioPort(enabled ? .speaker : .none)
    }

    func stop() {
        pump?.stop()
        pump = nil
        nativeCaptureStarted = nil
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        player.stop()
        engine.stop()
        callID = nil
        if sessionActive {
            try? AVAudioSession.sharedInstance().overrideOutputAudioPort(.none)
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            sessionActive = false
        }
        managedAudio = false
    }

    func resetMediaServices() {
        stop()
        engine = AVAudioEngine()
        player = AVAudioPlayerNode()
        engine.attach(player)
    }

    fileprivate enum AudioError: LocalizedError {
        case unavailable
        var errorDescription: String? { "No usable microphone route is available." }
    }
}

// Keep the hardware-rate tap in Float32 and convert the final mono samples to
// signed PCM explicitly. The common 48 kHz mono route bypasses AVAudioConverter.
private final class VoiceMicrophoneCapture: @unchecked Sendable {
    private let output: AVAudioFormat
    private let converter: AVAudioConverter?
    private let pump: VoicePCMPump

    init(input: AVAudioFormat, output: AVAudioFormat, pump: VoicePCMPump) throws {
        self.output = output
        self.pump = pump
        if input == output {
            converter = nil
        } else {
            guard let converter = AVAudioConverter(from: input, to: output) else {
                throw FamilyVoiceAudio.AudioError.unavailable
            }
            self.converter = converter
        }
    }

    func receive(_ buffer: AVAudioPCMBuffer) {
        pump.noteTap()
        guard buffer.frameLength > 0 else { return }
        guard let converter else {
            encode(buffer)
            return
        }
        let ratio = output.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * ratio)) + 32
        guard let converted = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: capacity) else { return }
        var supplied = false
        let status = converter.convert(to: converted, error: nil) { _, inputStatus in
            inputStatus.pointee = supplied ? .noDataNow : .haveData
            if supplied { return nil }
            supplied = true
            return buffer
        }
        if status != .error { encode(converted) }
    }

    private func encode(_ buffer: AVAudioPCMBuffer) {
        let length = Int(buffer.frameLength)
        guard length > 0, let samples = buffer.floatChannelData?[0] else { return }
        var pcm = Data(count: length * MemoryLayout<Int16>.size)
        pcm.withUnsafeMutableBytes { bytes in
            let output = bytes.bindMemory(to: Int16.self)
            for index in 0..<length {
                let sample = samples[index]
                let scaled = sample.isFinite ? max(-1, min(1, sample)) * 32_768 : 0
                output[index] = Int16(clamping: Int(scaled)).littleEndian
            }
        }
        pump.capture(pcm)
    }
}

// The audio tap only queues PCM. Python and playback scheduling use a separate
// serial queue, and both queues have bounded buffers to avoid growing call delay.
private final class VoicePCMPump: @unchecked Sendable {
    private static let frameBytes = 1_920
    private static let captureLimit = 11_520
    private let queue = DispatchQueue(label: "family.voice.pcm", qos: .userInteractive)
    private let lock = NSLock()
    private let callID: String
    private let player: AVAudioPlayerNode
    private let format: AVAudioFormat
    private let nativeProcessing: Bool
    private var captured = Data()
    private var tapDelivered = false
    private var pcmQueued = false
    private var timer: DispatchSourceTimer?
    private var playbackClock = FamilyVoicePlaybackClock()
    private var captureTicks = 0
    private var completionRefills = 0
    private var exchanges = 0
    private var fullPlaybackSlots = 0
    private var consumedBuffers = 0
    private var queueDepthSnapshot = 0
    private var previousExchange: UInt64?
    private var maximumExchangeGapMS = 0.0

    var playbackHealth: [String: Any] {
        lock.lock(); defer { lock.unlock() }
        return ["exchange_calls": exchanges, "capture_ticks": captureTicks,
                "completion_refills": completionRefills, "full_playback_slots": fullPlaybackSlots,
                "consumed_buffers": consumedBuffers, "scheduled_buffers": queueDepthSnapshot,
                "maximum_exchange_gap_ms": maximumExchangeGapMS]
    }

    init(callID: String, player: AVAudioPlayerNode, format: AVAudioFormat, nativeProcessing: Bool) {
        self.callID = callID
        self.player = player
        self.format = format
        self.nativeProcessing = nativeProcessing
    }

    var hasCapturedPCM: Bool {
        lock.lock()
        defer { lock.unlock() }
        return pcmQueued
    }

    func noteTap() {
        lock.lock()
        tapDelivered = true
        lock.unlock()
    }

    var captureStatus: String {
        lock.lock()
        defer { lock.unlock() }
        if pcmQueued { return "Microphone captured. Waiting for Reticulum to send audio." }
        if tapDelivered { return "Microphone input received. Waiting for audio conversion." }
        return "Waiting for iPad microphone input"
    }

    func capture(_ data: Data) {
        lock.lock()
        pcmQueued = true
        captured.append(data)
        let excess = captured.count - Self.captureLimit
        if excess > 0 { captured.removeFirst(excess) }
        lock.unlock()
    }

    func start() {
        queue.sync { playbackClock.start() }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(20), leeway: .milliseconds(2))
        timer.setEventHandler { [weak self] in self?.exchange() }
        self.timer = timer
        timer.resume()
    }

    func stop() {
        timer?.cancel()
        timer = nil
        queue.sync { playbackClock.stop() }
    }

    private func exchange(captureInput: Bool = true) {
        guard playbackClock.running else { return }
        lock.lock()
        let now = DispatchTime.now().uptimeNanoseconds
        if let previousExchange, now >= previousExchange {
            maximumExchangeGapMS = max(maximumExchangeGapMS, Double(now - previousExchange) / 1_000_000)
        }
        previousExchange = now
        exchanges += 1
        if captureInput { captureTicks += 1 } else { completionRefills += 1 }
        if playbackClock.available == 0 { fullPlaybackSlots += 1 }
        queueDepthSnapshot = playbackClock.scheduled
        // Only the capture timer consumes microphone PCM. A hardware completion
        // refills playback without stealing or duplicating the next capture tick.
        let input = captureInput ? captured : Data()
        if captureInput { captured = Data() }
        lock.unlock()

        let availableFrames = playbackClock.available
        var output = [UInt8](repeating: 0, count: Self.frameBytes * 3)
        let size = callID.withCString { id in
            input.withUnsafeBytes { pcm in
                output.withUnsafeMutableBufferPointer { received in
                    family_runtime_voice_exchange(id, pcm.bindMemory(to: UInt8.self).baseAddress,
                                                  pcm.count, nativeProcessing, received.baseAddress,
                                                  availableFrames * Self.frameBytes)
                }
            }
        }
        guard size > 0, size <= availableFrames * Self.frameBytes,
              size % Self.frameBytes == 0 else { return }
        // Fill unused playback slots in one exchange. One frame per timer can
        // never recover the backlog left by a coalesced or delayed callback.
        // The queue still holds at most three 20 ms buffers.
        for offset in stride(from: 0, to: size, by: Self.frameBytes) {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format,
                    frameCapacity: AVAudioFrameCount(Self.frameBytes / 2)),
                  let channel = buffer.floatChannelData?[0] else { return }
            buffer.frameLength = AVAudioFrameCount(Self.frameBytes / 2)
            for index in 0..<(Self.frameBytes / 2) {
                let byte = offset + index * 2
                let sample = UInt16(output[byte]) | UInt16(output[byte + 1]) << 8
                channel[index] = Float(Int16(bitPattern: sample)) / 32768
            }
            guard let lease = playbackClock.schedule() else { return }
            lock.lock(); queueDepthSnapshot = playbackClock.scheduled; lock.unlock()
            player.scheduleBuffer(buffer, completionCallbackType: .dataConsumed) { [weak self] _ in
                self?.queue.async { [weak self] in
                    guard let self, self.playbackClock.consumed(lease) else { return }
                    self.lock.lock()
                    self.consumedBuffers += 1
                    self.queueDepthSnapshot = self.playbackClock.scheduled
                    self.lock.unlock()
                    // Follow the audio hardware clock rather than waiting for the
                    // next timer. Python work remains off the render callback.
                    self.exchange(captureInput: false)
                }
            }
        }
    }
}
