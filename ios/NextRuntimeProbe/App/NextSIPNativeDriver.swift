import Foundation

typealias NextSIPEventSink = @MainActor (String, String, Int32, String) -> Void
typealias NextSIPExitSink = @MainActor (Int32) -> Void

struct NextSIPAccountValues: Sendable {
    let user: String
    let host: String
    let port: Int32
    let password: String
}

protocol NextSIPDriving: AnyObject {
    func start(_ account: NextSIPAccountValues, events: @escaping NextSIPEventSink, closed: @escaping NextSIPExitSink) -> Bool
    func command(_ operation: Int32, value: String?, callID: String) -> Bool
    func stop()
}

/// One Baresip instance per process. Callback closures capture their session
/// before crossing to the main actor, so late events cannot target a new call.
final class NextSIPNativeDriver: NextSIPDriving {
    private final class EventSlot: @unchecked Sendable {
        private let lock = NSLock()
        private var owner: UUID?
        private var sink: NextSIPEventSink?
        private var cancelled = false

        func begin(_ id: UUID, sink: @escaping NextSIPEventSink) -> Bool {
            lock.lock(); defer { lock.unlock() }
            guard owner == nil else { return false }
            owner = id; self.sink = sink; cancelled = false
            return true
        }
        func cancel(_ id: UUID) -> Bool {
            lock.lock(); defer { lock.unlock() }
            guard owner == id else { return false }
            cancelled = true
            return true
        }
        func blocked(_ id: UUID) -> Bool {
            lock.lock(); defer { lock.unlock() }
            return owner != id || cancelled
        }
        func finish(_ id: UUID) {
            lock.lock(); defer { lock.unlock() }
            if owner == id { owner = nil; sink = nil; cancelled = false }
        }
        func forward(_ state: String, peer: String, code: Int32, callID: String) {
            lock.lock()
            let receiver = sink, stopping = cancelled
            lock.unlock()
            if state == "ready" && stopping { family_sip_command(9, nil) }
            if let receiver {
                Task { @MainActor in receiver(state, peer, code, callID) }
            }
        }
    }
    private static let slot = EventSlot()
    private let id = UUID()

    func start(_ account: NextSIPAccountValues, events: @escaping NextSIPEventSink, closed: @escaping NextSIPExitSink) -> Bool {
        guard NextSIPNativeDriver.slot.begin(id, sink: events) else { return false }
        let owner = id
        DispatchQueue.global(qos: .userInitiated).async {
            var result: Int32 = 0
            if !NextSIPNativeDriver.slot.blocked(owner) {
                result = account.user.withCString { user in
                    account.host.withCString { host in
                        account.password.withCString { password in
                            family_sip_run(user, host, account.port, password) { state, peer, code, callID in
                                NextSIPNativeDriver.slot.forward(state.map { String(cString: $0) } ?? "engine_failed",
                                    peer: peer.map { String(cString: $0) } ?? "", code: code,
                                    callID: callID.map { String(cString: $0) } ?? "")
                            }
                        }
                    }
                }
            }
            NextSIPNativeDriver.slot.finish(owner)
            let exitCode = result
            Task { @MainActor in closed(exitCode) }
        }
        return true
    }

    func command(_ operation: Int32, value: String?, callID: String) -> Bool {
        guard !NextSIPNativeDriver.slot.blocked(id) else { return false }
        return callID.withCString { identifier in
            if let value { return value.withCString { family_sip_call_command(operation, $0, identifier) == 0 } }
            return family_sip_call_command(operation, nil, identifier) == 0
        }
    }

    func stop() {
        if NextSIPNativeDriver.slot.cancel(id) { family_sip_command(9, nil) }
    }
}
