// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import Security

/// Native-only consent. This record must never be returned by the loopback
/// API, placed in a QR, or encoded as a provider request.
struct NextCallWakeEnrollment: Codable {
    struct Caller: Codable, Equatable {
        let publicKey: Data
        let voiceAddress: String
        let name: String
    }
    var version = 1
    let provider: URL
    let audience: String
    let enrollmentCode: String
    let installation: Data
    let recipientPublicKey: Data
    var agreementPrivateKey: Data?
    let selectedCallers: [Caller]
    let policyDigest: String
    var revoking = false
    var mayBeRegistered = false

    enum Invalid: Error { case record }
    static let maximumBytes = 196_608

    func validated(installation expected: Data) throws -> Self {
        guard version == 1, installation.count == 32, installation == expected,
              let parts = URLComponents(url: provider, resolvingAgainstBaseURL: false),
              parts.scheme == "https", parts.host?.isEmpty == false,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              parts.port == nil || (1...65535).contains(parts.port!),
              audience.range(of: "^[A-Za-z0-9 _.-]{1,128}$", options: .regularExpression) != nil,
              enrollmentCode.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              policyDigest.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              recipientPublicKey.count == 64, selectedCallers.count <= 256,
              Set(selectedCallers.map(\.voiceAddress)).count == selectedCallers.count else { throw Invalid.record }
        if revoking {
            guard agreementPrivateKey == nil else { throw Invalid.record }
        } else {
            guard let key = agreementPrivateKey, key.count == 32,
                  try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: key).publicKey.rawRepresentation == recipientPublicKey.prefix(32) else { throw Invalid.record }
        }
        for caller in selectedCallers {
            guard caller.publicKey.count == 64, (1...256).contains(caller.name.utf8.count),
                  caller.name.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }),
                  try FamilyCallWake.voiceAddress(publicKey: caller.publicKey) == caller.voiceAddress else { throw Invalid.record }
        }
        return self
    }

    func context(installation: Data) -> NextCallWakeContext? {
        guard let valid = try? validated(installation: installation), !valid.revoking,
              let secret = valid.agreementPrivateKey else { return nil }
        return NextCallWakeContext(recipientPrivateKey: secret, recipientPublicKey: recipientPublicKey,
            audience: audience, approvedNames: Dictionary(uniqueKeysWithValues: selectedCallers.map { ($0.voiceAddress, $0.name) }))
    }

    mutating func beginRevocation() {
        // Local consent ends before the asynchronous provider removal starts.
        agreementPrivateKey = nil
        revoking = true
    }

    /// Deliberately separate DTO: never encode the enrollment record itself as
    /// a request. No bearer, names, agreement key or installation marker here.
    func subscription(token: Data?) throws -> Data {
        let valid = try validated(installation: installation)
        if let token, !(16...256).contains(token.count) { throw Invalid.record }
        struct Subscription: Encodable {
            let recipient_key: String
            let token: String?
            let callers: [String]
            func encode(to encoder: Encoder) throws {
                enum CodingKeys: String, CodingKey { case recipient_key, token, callers }
                var values = encoder.container(keyedBy: CodingKeys.self)
                try values.encode(recipient_key, forKey: .recipient_key)
                try values.encode(token, forKey: .token)
                try values.encode(callers, forKey: .callers)
            }
        }
        let hex: (Data) -> String = { $0.map { String(format: "%02x", $0) }.joined() }
        return try JSONEncoder().encode(Subscription(recipient_key: hex(valid.recipientPublicKey),
            token: valid.revoking ? nil : token.map(hex),
            callers: valid.revoking ? [] : valid.selectedCallers.map(\.voiceAddress).sorted()))
    }

    static func decode(_ data: Data, installation: Data) throws -> Self {
        guard data.count <= maximumBytes else { throw Invalid.record }
        return try JSONDecoder().decode(Self.self, from: data).validated(installation: installation)
    }
    func encoded(installation: Data) throws -> Data {
        let data = try JSONEncoder().encode(validated(installation: installation))
        guard data.count <= Self.maximumBytes else { throw Invalid.record }
        return data
    }
}

/// Missing enrollment and inaccessible Keychain are different outcomes. In
/// particular a pre-first-unlock error must never be interpreted as fresh consent.
@MainActor protocol NextCallWakeEnrollmentStoring {
    func load() throws -> Data?
    func save(_ data: Data?) throws
}
@MainActor struct NextCallWakeEnrollmentKeychain: NextCallWakeEnrollmentStoring {
    struct Failure: Error { let status: OSStatus }
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: (Bundle.main.bundleIdentifier ?? "org.meshchat.next.ios.runtimeprobe") + ".call-alerts",
         kSecAttrAccount as String: "explicit-consent-v1"]
    }
    func load() throws -> Data? {
        var request = query; request[kSecReturnData as String] = true
        var result: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data,
              data.count <= NextCallWakeEnrollment.maximumBytes else { throw Failure(status: status) }
        return data
    }
    func save(_ data: Data?) throws {
        guard let data else {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw Failure(status: status) }
            return
        }
        guard data.count <= NextCallWakeEnrollment.maximumBytes else { throw Failure(status: errSecParam) }
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let updated = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updated == errSecSuccess { return }
        guard updated == errSecItemNotFound else { throw Failure(status: updated) }
        var added = query; added.merge(attributes) { _, value in value }
        let status = SecItemAdd(added as CFDictionary, nil)
        guard status == errSecSuccess else { throw Failure(status: status) }
    }
}
