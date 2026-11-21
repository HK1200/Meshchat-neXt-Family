import Foundation
import Security

/// SIP account metadata stays in the existing store; secrets use own-app Keychain slots.
final class NextSIPPasswords {
    private let service: String
    init(service: String = "org.meshchat.next.ios.sip-accounts") { self.service = service }

    func perform(_ value: [String: Any]) throws -> [String: Any] {
        guard let operation = value["op"] as? String,
              let raw = value["account"] as? String,
              let account = UUID(uuidString: raw), raw.utf8.count == 36 else { throw Failure.invalid }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account.uuidString.lowercased()
        ]
        switch operation {
        case "password-save":
            guard let password = value["password"] as? String, !password.isEmpty,
                  password.utf8.count <= 256, !password.contains("\0") else { throw Failure.invalid }
            let update = [kSecValueData as String: Data(password.utf8)]
            let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
            if status == errSecItemNotFound {
                var add = query
                add[kSecValueData as String] = Data(password.utf8)
                add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
                guard SecItemAdd(add as CFDictionary, nil) == errSecSuccess else { throw Failure.unavailable }
            } else if status != errSecSuccess { throw Failure.unavailable }
            return ["ok": true]
        case "password-load":
            var read = query
            read[kSecReturnData as String] = true
            read[kSecMatchLimit as String] = kSecMatchLimitOne
            var item: CFTypeRef?
            guard SecItemCopyMatching(read as CFDictionary, &item) == errSecSuccess,
                  let data = item as? Data, let password = String(data: data, encoding: .utf8),
                  !password.isEmpty, password.utf8.count <= 256, !password.contains("\0") else { throw Failure.unavailable }
            return ["ok": true, "value": password]
        case "password-remove":
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw Failure.unavailable }
            return ["ok": true]
        default: throw Failure.invalid
        }
    }

    enum Failure: Error { case invalid, unavailable }
}
