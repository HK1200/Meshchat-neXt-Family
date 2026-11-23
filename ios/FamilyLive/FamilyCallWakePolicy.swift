// SPDX-License-Identifier: 0BSD
import CryptoKit
import Darwin
import Foundation

/// A cold-start read of this app's existing guardian approvals. It neither
/// enrolls a provider nor changes contacts, identity, or calling permissions.
struct FamilyCallWakePolicy {
    struct Caller: Equatable, Encodable {
        let publicKey: Data
        let voiceAddress: String
        let name: String
    }
    struct Approval: Equatable {
        let callers: [Caller]
        let digest: String
    }
    struct Intent: Equatable {
        let wake: FamilyCallWake
        let name: String
        let approvalDigest: String
    }
    private struct State: Decodable {
        struct Contact: Decodable {
            let name: String
            let addresses: [String: String]
            let identityPublicKey: String?
        }
        let setup_complete: Bool
        let voiceEnabled: Bool
        let contacts: [Contact]
    }
    enum Invalid: Error { case unavailable, approval }
    private let state: State
    var callingEnabled: Bool { state.setup_complete && state.voiceEnabled }
    struct Identity {
        let agreementPrivateKey: Data
        let publicKey: Data
        var messagingAddress: String { FamilyCallWakePolicy.messagingAddress(publicKey) }
        var voiceAddress: String { get throws { try FamilyCallWake.voiceAddress(publicKey: publicKey) } }
    }

    static func decode(_ bytes: Data) throws -> Self {
        guard bytes.count <= 33_554_432 else { throw Invalid.unavailable }
        let state = try JSONDecoder().decode(State.self, from: bytes)
        guard state.contacts.count <= 4096 else { throw Invalid.unavailable }
        return Self(state: state)
    }

    /// Check only explicitly selected, individually approved voice contacts.
    /// Room aliases, announces, messages and location data cannot grant access.
    func approval(selected: Set<String>, recipientPublicKey: Data) throws -> Approval {
        guard state.setup_complete, state.voiceEnabled, recipientPublicKey.count == 64,
              !selected.isEmpty, selected.count <= 256 else { throw Invalid.approval }
        let canonicalSelected = Set(selected.map { $0.lowercased() })
        guard canonicalSelected.count == selected.count else { throw Invalid.approval }
        let rows = state.contacts.filter { canonicalSelected.contains(($0.addresses["lxst"] ?? "").lowercased()) }
        guard rows.count == canonicalSelected.count,
              Set(rows.compactMap { $0.addresses["lxst"]?.lowercased() }).count == canonicalSelected.count else { throw Invalid.approval }
        let callers: [Caller] = try rows.map { row in
            guard let keyText = row.identityPublicKey, let voice = row.addresses["lxst"]?.lowercased(),
                  let messaging = row.addresses["lxmf"]?.lowercased(),
                  (1...256).contains(row.name.utf8.count),
                  row.name.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }) else { throw Invalid.approval }
            let key = try Self.publicKey(keyText)
            guard try FamilyCallWake.voiceAddress(publicKey: key) == voice,
                  Self.messagingAddress(key) == messaging else { throw Invalid.approval }
            return Caller(publicKey: key, voiceAddress: voice, name: row.name)
        }.sorted { $0.voiceAddress < $1.voiceAddress }
        struct Digest: Encodable { let recipient: Data; let callers: [Caller] }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let bytes = try encoder.encode(Digest(recipient: recipientPublicKey, callers: callers))
        return Approval(callers: callers, digest: Self.hex(Data(SHA256.hash(data: bytes))))
    }

    /// Native admission for a previously enrolled selection. The original
    /// consent digest must still match disk before and after decryption. No
    /// private key is retained in the result or passed to a provider.
    static func admit(_ payload: Data, support: URL, recipientPublicKey: Data,
                      audience: String, selected: Set<String>, approvalDigest: String,
                      now: Int) throws -> Intent {
        guard payload.count <= 5120, !selected.isEmpty, selected.count <= 256,
              approvalDigest.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil else { throw Invalid.approval }
        let before = try load(support: support).approval(selected: selected, recipientPublicKey: recipientPublicKey)
        guard before.digest == approvalDigest else { throw Invalid.approval }
        let privateKey = try identity(support: support, expectedPublicKey: recipientPublicKey)
        let wake = try FamilyCallWake.decode(payload, recipientPrivateKey: privateKey,
            recipientPublicKey: recipientPublicKey, audience: audience,
            approvedCallers: Set(before.callers.map(\.voiceAddress)), now: now)
        guard let caller = before.callers.first(where: { $0.voiceAddress == wake.callerVoice }),
              try load(support: support).approval(selected: selected, recipientPublicKey: recipientPublicKey) == before else { throw Invalid.approval }
        return Intent(wake: wake, name: caller.name, approvalDigest: before.digest)
    }

    func availableCallers(recipientPublicKey: Data) -> [Caller] {
        Set(state.contacts.compactMap { $0.addresses["lxst"]?.lowercased() }).sorted().compactMap { voice in
            try? approval(selected: [voice], recipientPublicKey: recipientPublicKey).callers.first
        }
    }

    static func load(support: URL) throws -> Self {
        try decode(read(support: support, name: "state.json", maximum: 33_554_432))
    }

    /// Identity stays native-only and is never part of Approval or its digest.
    static func ownIdentity(support: URL) throws -> Identity {
        let raw = try read(support: support, name: "identity", maximum: 64)
        guard raw.count == 64 else { throw Invalid.unavailable }
        let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: raw.prefix(32))
        let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: raw.suffix(32))
        return Identity(agreementPrivateKey: agreement.rawRepresentation,
            publicKey: agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation)
    }
    static func identity(support: URL, expectedPublicKey: Data) throws -> Data {
        let current = try ownIdentity(support: support)
        guard expectedPublicKey.count == 64, current.publicKey == expectedPublicKey else { throw Invalid.approval }
        return current.agreementPrivateKey
    }

    private static func publicKey(_ source: String) throws -> Data {
        let text = source.lowercased()
        guard text.range(of: #"\A[a-f0-9]{128}\z"#, options: .regularExpression) != nil else { throw Invalid.approval }
        return Data(stride(from: 0, to: 128, by: 2).map { offset in
            let start = text.index(text.startIndex, offsetBy: offset)
            return UInt8(text[start..<text.index(start, offsetBy: 2)], radix: 16)!
        })
    }
    static func messagingAddress(_ publicKey: Data) -> String {
        let name = Data(SHA256.hash(data: Data("lxmf.delivery".utf8)).prefix(10))
        let identity = Data(SHA256.hash(data: publicKey).prefix(16))
        return hex(Data(SHA256.hash(data: name + identity).prefix(16)))
    }
    private static func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }

    /// Fixed descendants only; never follow an imported folder/key symlink or
    /// block on a FIFO. Atomic state replacement is read through one descriptor.
    private static func read(support: URL, name: String, maximum: Int) throws -> Data {
        guard name == "identity" || name == "state.json" else { throw Invalid.unavailable }
        let base = Darwin.open(support.path, O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        guard base >= 0 else { throw Invalid.unavailable }; defer { Darwin.close(base) }
        let folder = openat(base, "FamilyTCP", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard folder >= 0 else { throw Invalid.unavailable }; defer { Darwin.close(folder) }
        let file = openat(folder, name, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        guard file >= 0 else { throw Invalid.unavailable }; defer { Darwin.close(file) }
        var before = stat()
        guard fstat(file, &before) == 0, before.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),
              before.st_uid == getuid(), before.st_size >= 0, before.st_size <= maximum,
              before.st_mode & 0o077 == 0 else { throw Invalid.unavailable }
        var bytes = [UInt8](repeating: 0, count: Int(before.st_size) + 1), count = 0
        while count < bytes.count {
            let size = bytes.withUnsafeMutableBytes { buffer in
                Darwin.read(file, buffer.baseAddress!.advanced(by: count), buffer.count - count)
            }
            if size == 0 { break }
            if size < 0 { if errno == EINTR { continue }; throw Invalid.unavailable }
            count += size
        }
        var after = stat()
        guard fstat(file, &after) == 0, count == before.st_size,
              after.st_size == before.st_size,
              after.st_mtimespec.tv_sec == before.st_mtimespec.tv_sec,
              after.st_mtimespec.tv_nsec == before.st_mtimespec.tv_nsec else { throw Invalid.unavailable }
        return Data(bytes.prefix(count))
    }
}
