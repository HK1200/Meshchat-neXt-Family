import Foundation

@MainActor
final class NextSIPBridge {
    private static let shared = NextSIPBridge()
    private let registration: NextSIPRegistration
    private init() {
        let network = NextSIPNetwork.shared
        let registration = NextSIPRegistration(network: network, driver: { NextSIPNativeDriver() })
        self.registration = registration
        network.setHandler { [weak registration] in
            Task { @MainActor in registration?.networkChanged() }
        }
    }
    nonisolated static func request(_ text: String) -> String {
        guard text.utf8.count <= 16 * 1024 else { return "{\"ok\":false}" }
        let operation = { @MainActor in NextSIPBridge.shared.perform(text) }
        if Thread.isMainThread { return MainActor.assumeIsolated { operation() } }
        return DispatchQueue.main.sync { MainActor.assumeIsolated { operation() } }
    }
    private func perform(_ text: String) -> String {
        guard let data = text.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let reply = try? JSONSerialization.data(withJSONObject: registration.perform(value)) else {
            return "{\"ok\":false}"
        }
        return String(decoding: reply, as: UTF8.self)
    }
}
