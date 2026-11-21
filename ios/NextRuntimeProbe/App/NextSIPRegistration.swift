import Foundation
import CoreFoundation
import UIKit
import AVFoundation

/// Own-process registration; call operations require an explicitly linked controller.
@MainActor
final class NextSIPRegistration {
    private final class Session {
        let id: String
        let context: String
        let driver: any NextSIPDriving
        var started = false
        var closing = false
        var closed = false
        var registered = false
        var calls: (any NextSIPCallManaging)?
        var events: [[String: Any]] = []
        init(id: String, context: String, driver: any NextSIPDriving) {
            self.id = id; self.context = context; self.driver = driver
        }
    }
    private let network: NextSIPNetwork
    private let makeDriver: () -> any NextSIPDriving
    private let makeCalls: ((any NextSIPDriving, @escaping ([String: Any]) -> Void) -> any NextSIPCallManaging)?
    private var session: Session?
    private static let states = Set(["ready", "registering", "registered", "registration_failed", "engine_failed", "stopped"])

    init(network: NextSIPNetwork, driver: @escaping () -> any NextSIPDriving,
         calls: ((any NextSIPDriving, @escaping ([String: Any]) -> Void) -> any NextSIPCallManaging)? = nil) {
        self.network = network; self.makeDriver = driver; self.makeCalls = calls
    }
    private func append(_ event: [String: Any], to current: Session) {
        guard session === current, !current.closed else { return }
        if current.events.count >= 250 {
            current.events = [["state": "engine_failed", "code": -1]]
            if !current.closing { current.closing = true; current.calls?.close(); current.driver.stop() }
            return
        }
        current.events.append(event)
    }
    func perform(_ value: [String: Any]) -> [String: Any] {
        guard let operation = value["op"] as? String else { return ["ok": false] }
        if operation == "capabilities" {
            let microphone: String
            switch AVAudioApplication.shared.recordPermission {
            case .granted: microphone = "granted"
            case .denied: microphone = "denied"
            case .undetermined: microphone = "not_determined"
            @unknown default: microphone = "unknown"
            }
            return ["ok": true, "calling_available": makeCalls != nil,
                    "default_speaker": UIDevice.current.userInterfaceIdiom == .pad,
                    "microphone_permission": microphone,
                    "system_call_error": session?.calls?.diagnostic ?? ""]
        }
        if operation == "networks" { return ["ok": true, "networks": network.snapshot()] }
        guard let id = value["session"] as? String,
              id.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return ["ok": false] }
        if operation == "open" {
            if let session, !session.closed { return ["ok": session.id == id && !session.closing] }
            guard let context = value["interface"] as? String, network.matches(context) else { return ["ok": false] }
            let current = Session(id: id, context: context, driver: makeDriver())
            session = current
            current.calls = makeCalls?(current.driver, { [weak self, weak current] event in
                guard let self, let current else { return }; self.append(event, to: current)
            })
            return ["ok": true, "calling_available": current.calls != nil]
        }
        guard let current = session, current.id == id else { return ["ok": false] }
        if operation == "poll" {
            let events = current.events
            current.events.removeAll(keepingCapacity: true)
            return ["ok": true, "events": events, "closed": current.closed]
        }
        if operation == "close" {
            if !current.closing && !current.closed {
                current.closing = true
                current.calls?.close()
                if current.started { current.driver.stop() }
                else { current.closed = true }
            }
            return ["ok": true, "closed": current.closed]
        }
        if ["dial", "answer", "hangup", "mute", "hold", "digit", "speaker"].contains(operation) {
            guard !current.closing, !current.closed, current.started, let calls = current.calls,
                  operation != "dial" || (current.registered && network.matches(current.context)) else { return ["ok": false] }
            return ["ok": calls.perform(value)]
        }
        guard operation == "start", !current.started, !current.closing, !current.closed,
              network.matches(current.context),
              let user = value["user"] as? String, let host = value["host"] as? String,
              let canonical = FamilySIPAddress.normalizedHost(host),
              let port = value["port"] as? Int, (1...65535).contains(port),
              let rawPort = value["port"] as? NSNumber,
              CFGetTypeID(rawPort) != CFBooleanGetTypeID(),
              FamilySIPAddress("sip:\(user)@\(FamilySIPAddress.hostForURI(canonical)):\(port)") != nil,
              let password = value["password"] as? String, !password.isEmpty,
              password.utf8.count <= 256, !password.contains("\0") else { return ["ok": false] }
        let account = NextSIPAccountValues(user: user, host: FamilySIPAddress.hostForURI(canonical),
                                          port: Int32(port), password: password)
        current.started = true
        let accepted = current.driver.start(account, events: { [weak self, weak current] state, peer, code, callID in
            guard let self, let current, self.session === current, !current.closed else { return }
            if ["incoming", "calling", "ringing", "progress", "connected", "ended", "muted", "audio_error", "command_failed"].contains(state) {
                if !current.closing, let calls = current.calls { calls.receive(state, peer: peer, code: code, id: callID) }
                else if state == "incoming", callID.range(of: "^[A-Za-z0-9_.-]{1,79}$", options: .regularExpression) != nil {
                    _ = current.driver.command(3, value: nil, callID: callID)
                }
                return
            }
            guard Self.states.contains(state) else { return }
            if state == "registered" { current.registered = true }
            if ["registration_failed", "engine_failed", "stopped"].contains(state) { current.registered = false }
            self.append(["state": state, "peer": "", "code": code], to: current)
            if current.closing && state == "ready" { current.driver.stop() }
        }, closed: { [weak self, weak current] code in
            guard let self, let current, self.session === current else { return }
            current.calls?.close()
            current.registered = false
            current.closed = true
            current.events.append(["state": "stopped", "peer": "", "code": code])
        })
        if !accepted { current.started = false; return ["ok": false] }
        return ["ok": true, "calling_available": current.calls != nil]
    }
    func networkChanged() {
        guard let session, !session.closing, !session.closed, !network.matches(session.context) else { return }
        session.closing = true
        session.calls?.close()
        if session.started { session.driver.stop() }
        else { session.closed = true }
    }
}
