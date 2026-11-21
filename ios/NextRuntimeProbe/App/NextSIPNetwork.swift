import Foundation
import Network

/// Describes only the current system route without binding or bypassing a VPN.
/// This is a logical context, not a claim that a second radio is separately usable.
final class NextSIPNetwork {
    enum Kind: String { case wifi, mobile, ethernet }
    static let shared = NextSIPNetwork()
    private let lock = NSLock()
    private let monitor: NWPathMonitor?
    private var route: [String: String]?
    private var changed: (() -> Void)?

    func setHandler(_ handler: (() -> Void)?) {
        lock.lock(); changed = handler; lock.unlock()
    }

    init(start: Bool = true) {
        monitor = start ? NWPathMonitor() : nil
        monitor?.pathUpdateHandler = { [weak self] path in
            let kind: Kind?
            if path.status != .satisfied { kind = nil }
            else if path.usesInterfaceType(.wifi) { kind = .wifi }
            else if path.usesInterfaceType(.cellular) { kind = .mobile }
            else if path.usesInterfaceType(.wiredEthernet) { kind = .ethernet }
            else { kind = nil }
            self?.update(kind)
        }
        monitor?.start(queue: DispatchQueue(label: "org.meshchat.next.sip-default-route"))
    }
    deinit { monitor?.cancel() }

    func update(_ kind: Kind?) {
        lock.lock()
        // A path callback invalidates the old context even if the connection
        // kind is unchanged (for example, moving between two Wi-Fi networks).
        route = kind.map { ["kind": $0.rawValue,
                            "interface": "ios-default-" + UUID().uuidString.lowercased(),
                            "address": "system-default"] }
        let callback = changed
        lock.unlock()
        callback?()
    }

    func snapshot() -> [[String: String]] {
        lock.lock(); defer { lock.unlock() }
        return route.map { [$0] } ?? []
    }

    func matches(_ context: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return route?["interface"] == context
    }
}
