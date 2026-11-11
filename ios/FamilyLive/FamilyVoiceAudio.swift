import AVFoundation
import Foundation
import UIKit

@MainActor
final class FamilyVoiceAudio {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var pump: VoicePCMPump?
    private var tapInstalled = false
    private var sessionActive = false
    private(set) var callID: String?

    init() { engine.attach(player) }

    var usingBuiltInSpeaker: Bool {
        AVAudioSession.sharedInstance().currentRoute.outputs.contains { $0.portType == .builtInSpeaker }
    }

    func start(callID: String) throws {
        guard self.callID != callID else { return }
        stop()
        do {
            try start(callID: callID, useVoiceProcessing: true)
        } catch {
            try start(callID: callID, useVoiceProcessing: false)
        }
    }

    private func start(callID: String, useVoiceProcessing: Bool) throws {
        let session = AVAudioSession.sharedInstance()
        do {
            var options: AVAudioSession.CategoryOptions = [.allowBluetooth]
            if UIDevice.current.userInterfaceIdiom == .pad {
                options.insert(.defaultToSpeaker)
            }
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: options)
            try session.setPreferredSampleRate(48_000)
            try session.setPreferredIOBufferDuration(0.02)
            try session.setActive(true)
            sessionActive = true

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
        } catch {
            stop()
            throw error
        }
    }

    var captureStatus: String {
        pump?.captureStatus ?? "Starting microphone"
    }

    func setSpeaker(_ enabled: Bool) throws {
        guard callID != nil else { return }
        try AVAudioSession.sharedInstance().overrideOutputAudioPort(enabled ? .speaker : .none)
    }

    func stop() {
        pump?.stop()
        pump = nil
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
    private var scheduled = 0

    init(callID: String, player: AVAudioPlayerNode, format: AVAudioFormat, nativeProcessing: Bool) {
        self.callID = callID
        self.player = player
        self.format = format
        self.nativeProcessing = nativeProcessing
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
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(20), leeway: .milliseconds(2))
        timer.setEventHandler { [weak self] in self?.exchange() }
        self.timer = timer
        timer.resume()
    }

    func stop() {
        timer?.cancel()
        timer = nil
        queue.sync {}
    }

    private func exchange() {
        lock.lock()
        let input = captured
        captured = Data()
        lock.unlock()

        var output = [UInt8](repeating: 0, count: Self.frameBytes)
        let canQueuePlayback = scheduled < 3
        let size = callID.withCString { id in
            input.withUnsafeBytes { pcm in
                output.withUnsafeMutableBufferPointer { received in
                    family_runtime_voice_exchange(id, pcm.bindMemory(to: UInt8.self).baseAddress,
                                                  pcm.count, nativeProcessing, received.baseAddress,
                                                  canQueuePlayback ? received.count : 0)
                }
            }
        }
        guard size == Self.frameBytes,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(size / 2)),
              let channel = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(size / 2)
        for index in 0..<(size / 2) {
            let sample = UInt16(output[index * 2]) | UInt16(output[index * 2 + 1]) << 8
            channel[index] = Float(Int16(bitPattern: sample)) / 32768
        }
        scheduled += 1
        player.scheduleBuffer(buffer, completionCallbackType: .dataConsumed) { [weak self] _ in
            self?.queue.async { [weak self] in
                if let self { self.scheduled -= 1 }
            }
        }
    }
}
