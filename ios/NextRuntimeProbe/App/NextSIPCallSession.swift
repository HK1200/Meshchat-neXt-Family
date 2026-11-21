import AVFoundation
import Combine
import CoreFoundation
import Foundation
import UIKit

@MainActor
protocol NextSIPCallManaging: AnyObject {
    func perform(_ value: [String: Any]) -> Bool
    func receive(_ state: String, peer: String, code: Int32, id: String)
    func close()
}

@MainActor
protocol NextSIPCallAudio: AnyObject {
    func prepare(managed: Bool) async -> Bool
    func speaker(_ enabled: Bool) -> Bool
    func finish(managed: Bool)
}

@MainActor
final class NextSIPSystemAudio: NextSIPCallAudio {
    func prepare(managed: Bool) async -> Bool {
        let allowed = await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
        guard allowed else { return false }
        do {
            try FamilyCallAudioSession.configure()
            if !managed { try AVAudioSession.sharedInstance().setActive(true) }
            return true
        } catch { return false }
    }
    func speaker(_ enabled: Bool) -> Bool {
        guard !FamilyCallAudioSession.hasExternalOutput else { return false }
        guard enabled || UIDevice.current.userInterfaceIdiom != .pad else { return false }
        do {
            try AVAudioSession.sharedInstance().overrideOutputAudioPort(enabled ? .speaker : .none)
            return true
        } catch { return false }
    }
    func finish(managed: Bool) {
        if !managed { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
    }
}

/// Owns one exact Baresip call; CallKit/permission awaits cannot act on a later call.
@MainActor
final class NextSIPCallSession: NextSIPCallManaging {
    private final class Call {
        let id: String; let peer: String; let incoming: Bool
        var started: Bool; var connected = false; var ending = false; var muted = false; var answering = false
        init(id: String, peer: String, incoming: Bool) {
            self.id = id; self.peer = peer; self.incoming = incoming; self.started = incoming
        }
        var key: FamilySystemCallKey { FamilySystemCallKey(service: .sip, id: id) }
    }
    private let driver: any NextSIPDriving
    private let system: FamilySystemCalls
    private let audio: any NextSIPCallAudio
    private let emit: ([String: Any]) -> Void
    private var current: Call?
    private var retired: [String] = []
    private var closed = false
    private var observations = Set<AnyCancellable>()

    init(driver: any NextSIPDriving, system: FamilySystemCalls,
         audio: any NextSIPCallAudio, observeAudio: Bool = true,
         emit: @escaping ([String: Any]) -> Void) {
        self.driver = driver; self.system = system; self.audio = audio; self.emit = emit
        guard observeAudio else { return }
        system.$audioReady.dropFirst().sink { [weak self] _ in
            Task { @MainActor in self?.audioChanged() }
        }.store(in: &observations)
        NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification).sink { [weak self] note in
            let type = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber)?.uintValue
            let options = (note.userInfo?[AVAudioSessionInterruptionOptionKey] as? NSNumber)?.uintValue ?? 0
            Task { @MainActor in
                guard let self, let call = self.current else { return }
                if type == AVAudioSession.InterruptionType.began.rawValue {
                    _ = self.command(8, call: call)
                } else if options & AVAudioSession.InterruptionOptions.shouldResume.rawValue != 0 {
                    if await self.audio.prepare(managed: self.system.owns(call.key)), self.current === call {
                        self.audioChanged()
                    }
                } else { self.end(call) }
            }
        }.store(in: &observations)
        NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification).sink { [weak self] _ in
            Task { @MainActor in self?.audioChanged() }
        }.store(in: &observations)
        NotificationCenter.default.publisher(for: AVAudioSession.mediaServicesWereResetNotification).sink { [weak self] _ in
            Task { @MainActor in self?.close(); self?.driver.stop() }
        }.store(in: &observations)
    }

    func perform(_ value: [String: Any]) -> Bool {
        guard !closed, let operation = value["op"] as? String,
              let id = value["call_id"] as? String,
              id.range(of: "^[A-Za-z0-9_.-]{1,79}$", options: .regularExpression) != nil else { return false }
        if operation == "dial" {
            guard current == nil, !system.hasCall, !retired.contains(id),
                  let raw = value["peer"] as? String, let address = FamilySIPAddress(raw) else { return false }
            let call = Call(id: id, peer: address.uri, incoming: false)
            current = call; event("calling", call: call)
            if !track(call) { finish(call, failed: true); return false }
            return true
        }
        guard let call = current, call.id == id, !call.ending else { return false }
        switch operation {
        case "answer":
            guard call.incoming, !call.connected, !call.answering else { return false }
            call.answering = true
            if system.owns(call.key) { Task { await system.requestAnswer(call.key) } }
            else { Task { if await prepare(call) { if !begin(call, answer: true) { end(call) } } else { end(call) } } }
            return true
        case "hangup":
            if system.owns(call.key) { Task { await system.requestEnd(call.key) } }
            else { end(call) }
            return true
        case "mute":
            guard let muted = boolean(value["value"]) else { return false }
            if system.owns(call.key) { Task { await system.requestMute(call.key, muted: muted) }; return true }
            return setMuted(muted, call: call)
        case "speaker":
            guard let enabled = boolean(value["value"]), call.connected else { return false }
            return audio.speaker(enabled)
        case "hold":
            guard let held = boolean(value["value"]), call.connected else { return false }
            return command(6, held ? "1" : "0", call: call)
        case "digit":
            guard call.connected, let digit = value["digit"] as? String, digit.count == 1,
                  "0123456789*#ABCD".contains(digit) else { return false }
            return command(5, digit, call: call)
        default: return false
        }
    }
    private func boolean(_ value: Any?) -> Bool? {
        guard let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }
    private func track(_ call: Call) -> Bool {
        if system.enabled {
            return system.track(call.key, name: call.peer, incoming: call.incoming,
                actions: FamilySystemCallActions(
                    prepareAudio: { [weak self, weak call] in
                        guard let self, let call else { return false }; return await self.prepare(call)
                    }, start: { [weak self, weak call] in
                        guard let self, let call else { return false }; return self.begin(call, answer: false)
                    }, answer: { [weak self, weak call] in
                        guard let self, let call else { return false }; return self.begin(call, answer: true)
                    }, end: { [weak self, weak call] in if let call { self?.end(call) } },
                    mute: { [weak self, weak call] muted in
                        guard let self, let call else { return false }; return self.setMuted(muted, call: call)
                    }))
        }
        if !call.incoming {
            Task { if await prepare(call) { if !begin(call, answer: false) { end(call) } } else { end(call) } }
        }
        return true
    }
    private func prepare(_ call: Call) async -> Bool {
        guard current === call, !call.ending, !closed else { return false }
        let allowed = await audio.prepare(managed: system.owns(call.key))
        guard current === call, !call.ending, !closed else { return false }
        if !allowed { event("audio_error", call: call, code: -1) }
        return allowed
    }
    private func begin(_ call: Call, answer: Bool) -> Bool {
        guard current === call, !call.ending, !closed, answer == call.incoming,
              system.allowsAudio(call.key), command(answer ? 2 : 1, answer ? nil : call.peer, call: call) else { return false }
        call.started = true
        if call.muted { _ = command(4, "1", call: call) }
        return true
    }
    private func command(_ operation: Int32, _ value: String? = nil, call: Call) -> Bool {
        guard current === call, !closed else { return false }
        return driver.command(operation, value: value, callID: call.id)
    }
    private func setMuted(_ muted: Bool, call: Call) -> Bool {
        guard current === call, !call.ending else { return false }
        if call.started && !command(4, muted ? "1" : "0", call: call) { return false }
        call.muted = muted; event("muted", call: call, code: muted ? 1 : 0)
        return true
    }
    func receive(_ state: String, peer: String, code: Int32, id: String) {
        guard !closed else { return }
        if state == "incoming" {
            guard id.range(of: "^[A-Za-z0-9_.-]{1,79}$", options: .regularExpression) != nil,
                  !retired.contains(id) else { return }
            if current?.id == id { return }
            guard current == nil, !system.hasCall, let address = FamilySIPAddress(peer) else {
                _ = driver.command(3, value: nil, callID: id); return
            }
            let call = Call(id: id, peer: address.uri, incoming: true)
            current = call
            if track(call) { event("incoming", call: call) }
            else { end(call) }
            return
        }
        guard let call = current, call.id == id else { return }
        switch state {
        case "calling", "ringing", "progress": if !call.ending { event(state, call: call, code: code) }
        case "connected":
            guard !call.ending else { return }
            call.connected = true; system.update(call.key, connected: true); event(state, call: call, code: code)
        case "ended": finish(call)
        case "muted": call.muted = code != 0; event(state, call: call, code: code)
        case "audio_error", "command_failed":
            event(state, call: call, code: code)
            if state == "audio_error" || !call.connected || call.ending { end(call) }
        default: break
        }
    }
    private func event(_ state: String, call: Call, code: Int32 = 0) {
        emit(["state": state, "peer": call.peer, "native_id": call.id, "code": code])
    }
    private func end(_ call: Call) {
        guard current === call, !call.ending else { return }
        call.ending = true
        if call.started && !command(3, call: call) { driver.stop() }
        // Retire immediately even if the native hangup fails: later events may
        // not resurrect this call, and the engine still owns the final teardown.
        finish(call)
    }
    private func finish(_ call: Call, failed: Bool = false) {
        guard current === call else { return }
        let managed = system.owns(call.key)
        current = nil; retired.append(call.id)
        if retired.count > 256 { retired.removeFirst(retired.count - 256) }
        system.finish(call.key, failed: failed)
        audio.finish(managed: managed); event("ended", call: call)
    }
    private func audioChanged() {
        guard let call = current, call.connected, !call.ending else { return }
        if system.allowsAudio(call.key) {
            _ = command(7, call: call); _ = command(4, call.muted ? "1" : "0", call: call)
        } else { _ = command(8, call: call) }
    }
    func close() {
        guard !closed else { return }
        if let call = current { end(call) }
        closed = true; observations.removeAll()
    }
}
