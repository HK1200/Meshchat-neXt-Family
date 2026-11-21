import Foundation
import Security

/// Node passwords stay in this app's Keychain, never in the message database.
final class NextMeshCoreSecrets {
    static let shared = NextMeshCoreSecrets()
    private let service: String

    init(service: String = "org.meshchat.next.meshcore.node-passwords") {
        self.service = service
    }

    func request(_ text: String) -> String {
        let reply: [String: Any]
        do { reply = try perform(text) }
        catch { reply = ["error": "Secure node password operation could not be completed."] }
        guard let data = try? JSONSerialization.data(withJSONObject: reply),
              let result = String(data: data, encoding: .utf8) else { return "{}" }
        return result
    }

    private func perform(_ text: String) throws -> [String: Any] {
        guard text.utf8.count <= 4096, let data = text.data(using: .utf8),
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let owner = value["owner"] as? String, let peer = value["peer"] as? String,
              let role = value["role"] as? String, ["member", "admin"].contains(role),
              owner.utf8.count == 64, peer.utf8.count == 64,
              owner.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              peer.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              let operation = value["operation"] as? String else { throw Failure.invalid }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: owner + ":" + peer + ":" + role
        ]
        switch operation {
        case "has":
            let status = SecItemCopyMatching(query as CFDictionary, nil)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw Failure.keychain }
            return ["value": status == errSecSuccess]
        case "load":
            var read = query
            read[kSecReturnData as String] = true
            read[kSecMatchLimit as String] = kSecMatchLimitOne
            var item: CFTypeRef?
            guard SecItemCopyMatching(read as CFDictionary, &item) == errSecSuccess,
                  let bytes = item as? Data, let password = String(data: bytes, encoding: .utf8) else { throw Failure.keychain }
            return ["value": password]
        case "save":
            guard let password = value["password"] as? String,
                  !password.contains("\0"), password.utf8.count <= 64 else { throw Failure.invalid }
            let update = [kSecValueData as String: Data(password.utf8)]
            let changed = SecItemUpdate(query as CFDictionary, update as CFDictionary)
            if changed == errSecItemNotFound {
                var add = query
                add[kSecValueData as String] = Data(password.utf8)
                add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
                guard SecItemAdd(add as CFDictionary, nil) == errSecSuccess else { throw Failure.keychain }
            } else if changed != errSecSuccess { throw Failure.keychain }
            return ["value": true]
        case "forget":
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw Failure.keychain }
            return ["value": true]
        default: throw Failure.invalid
        }
    }

    private enum Failure: Error { case invalid, keychain }
}
