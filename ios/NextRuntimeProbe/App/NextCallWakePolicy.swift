// SPDX-License-Identifier: 0BSD
import Foundation

/// Public, authenticated loopback metadata. No private identity or provider
/// bearer may be decoded from this response.
struct NextCallWakePolicy: Decodable {
    struct Contact: Decodable {
        let name: String?
        let addresses: [String: String]
        let identityPublicKey: String?
    }
    let address: String
    let voiceAddress: String
    let identityPublicKey: String
    let enabled: Bool
    let contacts: [Contact]
    let policyDigest: String
    enum Invalid: Error { case policy }

    static func publicKey(_ hex: String) throws -> Data {
        guard hex.utf8.count == 128,
              hex.range(of: #"\A[a-f0-9]{128}\z"#, options: .regularExpression) != nil else { throw Invalid.policy }
        var bytes = Data()
        for offset in stride(from: 0, to: hex.count, by: 2) {
            let start = hex.index(hex.startIndex, offsetBy: offset), end = hex.index(start, offsetBy: 2)
            guard let byte = UInt8(hex[start..<end], radix: 16) else { throw Invalid.policy }
            bytes.append(byte)
        }
        return bytes
    }

    func ownIdentity(support: URL) throws -> NextCallWakeIdentity {
        let publicKey = try Self.publicKey(identityPublicKey)
        guard try NextCallWakeIdentity.messagingAddress(publicKey: publicKey) == address,
              try FamilyCallWake.voiceAddress(publicKey: publicKey) == voiceAddress else { throw Invalid.policy }
        return try NextCallWakeIdentity.load(support: support, expectedPublicKey: publicKey,
                                            address: address, voiceAddress: voiceAddress)
    }

    func callers(selected: Set<String>) throws -> [NextCallWakeEnrollment.Caller] {
        guard enabled, !selected.isEmpty, selected.count <= 256,
              policyDigest.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil else { throw Invalid.policy }
        let matches = contacts.filter { selected.contains($0.addresses["voice"] ?? "") }
        guard matches.count == selected.count,
              Set(matches.compactMap { $0.addresses["voice"] }).count == selected.count else { throw Invalid.policy }
        return try matches.map { row in
            guard let hex = row.identityPublicKey, let voice = row.addresses["voice"],
                  let address = row.addresses["lxmf"] else { throw Invalid.policy }
            let publicKey = try Self.publicKey(hex)
            guard try NextCallWakeIdentity.messagingAddress(publicKey: publicKey) == address,
                  try FamilyCallWake.voiceAddress(publicKey: publicKey) == voice else { throw Invalid.policy }
            return NextCallWakeEnrollment.Caller(publicKey: publicKey, voiceAddress: voice,
                name: row.name?.isEmpty == false ? row.name! : "Reticulum contact")
        }.sorted { $0.voiceAddress < $1.voiceAddress }
    }
}
