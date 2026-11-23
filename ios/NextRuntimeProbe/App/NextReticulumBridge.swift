import AVFoundation
import Foundation
import UIKit

/// Commands are queued for Python; native callbacks never wait for the
/// interpreter while CallKit owns the main actor. PCM has its own C/GIL path.
@MainActor
final class NextReticulumDriver: NextCallDriving {
    let audio = FamilyVoiceAudio()
    var names: [String: String] = [:]
    var identifier = ""
    var connected = false
    var events: [[String: Any]] = []
    private var audioFailureReported = false

    func bind(_ id: String, peer: String, name: String) {
        if identifier != id {
            audio.stop(); next_probe_set_voice_muted(false)
            connected = false; audioFailureReported = false
        }
        identifier = id; names = [peer: name]
    }
    func enqueue(_ operation: String, id: String, value: Bool? = nil) {
        guard !id.isEmpty else { return }
        if operation == "hangup", events.contains(where: { $0["operation"] as? String == operation && $0["call_id"] as? String == id }) { return }
        guard events.count < 250 else {
            audio.stop(); next_probe_set_voice_muted(true)
            events = [["operation": "audio_error", "call_id": id]]
            return
        }
        var event: [String: Any] = ["operation": operation, "call_id": id]
        if let value { event["value"] = value }
        events.append(event)
    }
    nonisolated func command(_ operation: Int32, value: String?, callID: String) -> Bool {
        guard Thread.isMainThread else { return false }
        return MainActor.assumeIsolated { perform(operation, value: value, callID: callID) }
    }
    private func perform(_ operation: Int32, value: String?, callID: String) -> Bool {
        guard callID == identifier else { return false }
        switch operation {
        case 1: enqueue("dial", id: callID)
        case 2: enqueue("answer", id: callID)
        case 3:
            audio.stop(); next_probe_set_voice_muted(true)
            enqueue("hangup", id: callID)
        case 4:
            guard value == "0" || value == "1" else { return false }
            let muted = value == "1"
            // Stop capture at the native boundary immediately, before the
            // asynchronous signaling loop applies its matching mute state.
            next_probe_set_voice_muted(muted)
            enqueue("mute", id: callID, value: muted)
        case 7:
            guard connected else { return false }
            do {
                try audio.start(callID: callID,
                    managedAudio: FamilySystemCalls.shared.owns(FamilySystemCallKey(service: .reticulum, id: callID)))
            } catch { reportAudioFailure(); return false }
        case 8: audio.stop()
        default: return false
        }
        return true
    }
    func recoverCapture() {
        guard connected, audio.callID == identifier else { return }
        do { try audio.recoverStalledCapture() } catch { reportAudioFailure() }
    }
    private func reportAudioFailure() {
        guard !audioFailureReported else { return }
        audioFailureReported = true
        audio.stop(); next_probe_set_voice_muted(true)
        enqueue("audio_error", id: identifier)
    }
    nonisolated func stop() {
        guard Thread.isMainThread else { return }
        MainActor.assumeIsolated {
            audio.stop(); next_probe_set_voice_muted(true)
            enqueue("hangup", id: identifier)
        }
    }
}

@MainActor
private final class NextReticulumAudio: NextSIPCallAudio {
    let driver: NextReticulumDriver
    private let session = NextSIPSystemAudio()
    init(_ driver: NextReticulumDriver) { self.driver = driver }
    func prepare(managed: Bool) async -> Bool { await session.prepare(managed: managed) }
    func speaker(_ enabled: Bool) -> Bool { session.speaker(enabled) }
    func finish(managed: Bool) { driver.audio.stop(); session.finish(managed: managed) }
}

@MainActor
final class NextReticulumBridge {
    private static let shared = NextReticulumBridge()
    private var session: String?
    private var calls: NextSIPCallSession?
    private var driver: NextReticulumDriver?

    nonisolated static func request(_ text: String) -> String {
        guard text.utf8.count <= 16_384 else { return "{\"ok\":false}" }
        let operation = { @MainActor in shared.perform(text) }
        if Thread.isMainThread { return MainActor.assumeIsolated { operation() } }
        return DispatchQueue.main.sync { MainActor.assumeIsolated { operation() } }
    }
    private func perform(_ text: String) -> String {
        guard let data = text.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let result = try? JSONSerialization.data(withJSONObject: perform(value)) else { return "{\"ok\":false}" }
        return String(decoding: result, as: UTF8.self)
    }
    func perform(_ value: [String: Any]) -> [String: Any] {
        guard let operation = value["op"] as? String,
              let identifier = value["session"] as? String,
              identifier.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return ["ok": false] }
        if operation == "open" {
            if let session {
                guard session == identifier else { return ["ok": false] }
                if calls?.isClosed != true { return ["ok": true] }
                driver?.stop(); self.calls = nil; self.driver = nil; self.session = nil
            }
            let driver = NextReticulumDriver()
            self.driver = driver; session = identifier
            calls = NextSIPCallSession(driver: driver, system: FamilySystemCalls.shared,
                audio: NextReticulumAudio(driver), service: .reticulum,
                normalizePeer: { $0.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil ? $0.lowercased() : nil },
                displayName: { [weak driver] peer in driver?.names[peer] ?? "Reticulum caller" },
                wakeRouter: NextReticulumWakeRouter.shared,
                emit: { [weak driver] event in
                    if event["state"] as? String == "ended", let id = event["native_id"] as? String {
                        driver?.enqueue("hangup", id: id)
                    }
                })
            return ["ok": true]
        }
        guard session == identifier, let calls, let driver else { return ["ok": false] }
        if operation == "call_policy_invalid" {
            NextCallWakeOwner.shared.registration.pauseForReview()
            return ["ok": true]
        }
        if operation == "call_policy" {
            guard let digest = value["digest"] as? String,
                  digest.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil else { return ["ok": false] }
            NextCallWakeOwner.shared.policyChanged(digest)
            return ["ok": true]
        }
        if operation == "close" {
            calls.close(); driver.stop()
            self.calls = nil; self.driver = nil; session = nil
            return ["ok": true]
        }
        if operation == "capabilities" {
            return ["ok": true, "microphone_permission": AVAudioApplication.shared.recordPermission == .granted ? "granted" : "not_granted",
                    "capture_status": driver.audio.captureStatus, "system_call_error": calls.diagnostic,
                    "speaker": driver.audio.usingBuiltInSpeaker, "external_audio": FamilyCallAudioSession.hasExternalOutput]
        }
        if operation == "poll" {
            guard !calls.isClosed else { return ["ok": false] }
            driver.recoverCapture()
            let events = driver.events; driver.events.removeAll(keepingCapacity: true)
            return ["ok": true, "events": events]
        }
        guard let callID = value["call_id"] as? String,
              callID.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return ["ok": false] }
        if operation == "dial" || operation == "state" && value["state"] as? String == "incoming" {
            guard !calls.hasActiveCall, let peer = value["peer"] as? String,
                  peer.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil else { return ["ok": false] }
            let name = (value["name"] as? String ?? "Reticulum caller")
                .filter { !$0.unicodeScalars.contains(where: { $0.value < 32 }) }
            driver.bind(callID, peer: peer.lowercased(), name: String(name.prefix(128)))
        }
        if operation == "state" {
            guard let state = value["state"] as? String,
                  ["incoming", "ringing", "connected", "ended"].contains(state),
                  callID == driver.identifier, let peer = value["peer"] as? String else { return ["ok": false] }
            if state == "connected" { driver.connected = true }
            if state == "ended" { driver.connected = false }
            calls.receive(state, peer: peer, code: 0, id: callID)
            if state == "ended" { driver.audio.stop() }
            return ["ok": true]
        }
        return ["ok": calls.perform(value)]
    }
}
