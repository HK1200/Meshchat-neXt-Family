import Foundation
import CoreFoundation

/// An own-process SIP registration session. Calling is kept unavailable until
/// the CallKit/audio adapter is installed; this layer cannot place a call.
@MainActor
final class NextSIPRegistration {
    private final class Session {
        let id: String
        let context: String
        let driver: any NextSIPDriving
        var started = false
        var closing = false
        var closed = false
        var events: [[String: Any]] = []
        init(id: String, context: String, driver: any NextSIPDriving) {
            self.id = id; self.context = context; self.driver = driver
        }
    }
    private let network: NextSIPNetwork
    private let makeDriver: () -> any NextSIPDriving
    private var session: Session?
    private static let states = Set(["ready", "registering", "registered", "registration_failed", "engine_failed", "stopped"])

    init(network: NextSIPNetwork, driver: @escaping () -> any NextSIPDriving) {
        self.network = network; self.makeDriver = driver
    }
    func perform(_ value: [String: Any]) -> [String: Any] {
        guard let operation = value["op"] as? String else { return ["ok": false] }
        if operation == "networks" { return ["ok": true, "networks": network.snapshot()] }
        guard let id = value["session"] as? String,
              id.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return ["ok": false] }
        if operation == "open" {
            if let session, !session.closed { return ["ok": session.id == id && !session.closing] }
            guard let context = value["interface"] as? String, network.matches(context) else { return ["ok": false] }
            session = Session(id: id, context: context, driver: makeDriver())
            return ["ok": true, "calling_available": false]
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
                if current.started { current.driver.stop() }
                else { current.closed = true }
            }
            return ["ok": true, "closed": current.closed]
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
        let accepted = current.driver.start(account, events: { [weak self, weak current] state, _, code, callID in
            guard let self, let current, self.session === current, !current.closed else { return }
            if state == "incoming" {
                // Registration-only integration cannot answer or expose a call.
                if callID.range(of: "^[A-Za-z0-9_.-]{1,79}$", options: .regularExpression) != nil {
                    _ = current.driver.command(3, value: nil, callID: callID)
                }
                return
            }
            guard Self.states.contains(state) else { return }
            if current.events.count >= 250 {
                current.events = [["state": "engine_failed", "code": -1]]
                if !current.closing { current.closing = true; current.driver.stop() }
                return
            }
            // The registration layer never forwards caller addresses or audio.
            current.events.append(["state": state, "peer": "", "code": code])
            if current.closing && state == "ready" { current.driver.stop() }
        }, closed: { [weak self, weak current] code in
            guard let self, let current, self.session === current else { return }
            current.closed = true
            current.events.append(["state": "stopped", "peer": "", "code": code])
        })
        if !accepted { current.started = false; return ["ok": false] }
        return ["ok": true, "calling_available": false]
    }
    func networkChanged() {
        guard let session, !session.closing, !session.closed, !network.matches(session.context) else { return }
        session.closing = true
        if session.started { session.driver.stop() }
        else { session.closed = true }
    }
}
