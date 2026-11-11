import AVFoundation
import Foundation

@MainActor
final class FamilyVoiceAudio {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var pump: VoicePCMPump?
    private var tapInstalled = false
    private var sessionActive = false
    private(set) var callID: String?

    init() { engine.attach(player) }

    func start(callID: String) throws {
        guard self.callID != callID else { return }
        stop()
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetooth])
            try session.setPreferredSampleRate(48_000)
            try session.setPreferredIOBufferDuration(0.02)
            try session.setActive(true)
            sessionActive = true

            let input = engine.inputNode
            let hardware = input.outputFormat(forBus: 0)
            guard hardware.sampleRate > 0, hardware.channelCount > 0,
                  let pcm = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 48_000, channels: 1, interleaved: true),
                  let playback = AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 1),
                  let converter = AVAudioConverter(from: hardware, to: pcm) else {
                throw AudioError.unavailable
            }
            engine.connect(player, to: engine.mainMixerNode, format: playback)
            let pump = VoicePCMPump(callID: callID, player: player, format: playback)
            self.pump = pump
            input.installTap(onBus: 0, bufferSize: 960, format: hardware) { buffer, _ in
                let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * pcm.sampleRate / hardware.sampleRate)) + 8
                guard let converted = AVAudioPCMBuffer(pcmFormat: pcm, frameCapacity: capacity) else { return }
                var sent = false
                let status = converter.convert(to: converted, error: nil) { _, result in
                    if sent {
                        result.pointee = .noDataNow
                        return nil
                    }
                    sent = true
                    result.pointee = .haveData
                    return buffer
                }
                guard status != .error, let samples = converted.int16ChannelData?[0], converted.frameLength > 0 else { return }
                pump.capture(Data(bytes: samples, count: Int(converted.frameLength) * 2))
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

    private enum AudioError: LocalizedError {
        case unavailable
        var errorDescription: String? { "No usable microphone route is available." }
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
    private var captured = Data()
    private var timer: DispatchSourceTimer?
    private var scheduled = 0

    init(callID: String, player: AVAudioPlayerNode, format: AVAudioFormat) {
        self.callID = callID
        self.player = player
        self.format = format
    }

    func capture(_ data: Data) {
        lock.lock()
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
        let size = callID.withCString { id in
            input.withUnsafeBytes { pcm in
                output.withUnsafeMutableBufferPointer { received in
                    family_runtime_voice_exchange(id, pcm.bindMemory(to: UInt8.self).baseAddress,
                                                  pcm.count, received.baseAddress, received.count)
                }
            }
        }
        guard size == Self.frameBytes, scheduled < 3,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(size / 2)),
              let channel = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(size / 2)
        for index in 0..<(size / 2) {
            let sample = UInt16(output[index * 2]) | UInt16(output[index * 2 + 1]) << 8
            channel[index] = Float(Int16(bitPattern: sample)) / 32768
        }
        scheduled += 1
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            self?.queue.async { [weak self] in
                if let self { self.scheduled -= 1 }
            }
        }
    }
}
