// SPDX-License-Identifier: 0BSD
import CryptoKit
import Darwin
import Foundation

/// Identity files use Reticulum's standard 64-byte private-key format. Restore
/// is staged and applied before Python starts; a live identity is never swapped.
enum NextIdentityRecovery {
    struct Key: Equatable {
        let bytes: Data
        let hash: String
        let messagingAddress: String
        init(_ bytes: Data) throws {
            guard bytes.count == 64 else { throw Failure.invalidKey }
            let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: bytes.prefix(32))
            let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: bytes.suffix(32))
            let publicKey = agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation
            self.bytes = bytes
            hash = Data(SHA256.hash(data: publicKey).prefix(16)).map { String(format: "%02x", $0) }.joined()
            messagingAddress = try NextCallWakeIdentity.messagingAddress(publicKey: publicKey)
        }
    }
    enum Failure: LocalizedError {
        case invalidKey, unavailable, changed, savedCopy, invalidPending
        var errorDescription: String? {
            switch self {
            case .invalidKey: "Choose a standard 64-byte Reticulum identity file. A contact QR or public address is not an identity backup."
            case .unavailable: "The private identity file could not be read or saved safely. Check your current identity before trying again."
            case .changed: "The current identity changed after this restore was prepared. Cancel the restore and select the backup again."
            case .savedCopy: "The saved copy of your current identity could not be verified. Your current identity has not been replaced."
            case .invalidPending: "The pending identity restore is invalid. Cancel it in Identity backup before restarting."
            }
        }
    }
    struct Pending: Codable {
        let version: Int
        let originalDigest: String?
        let replacementHash: String
        let privateKey: String
    }
    struct Status {
        let current: Key?
        let pending: Key?
        let saved: [Key]
        let pendingError: String?
        let savedError: String?
    }
    static var identityDirectoryName: String {
        #if targetEnvironment(simulator)
        "reticulum-simulator"
        #else
        "reticulum"
        #endif
    }
    private static let lock = NSRecursiveLock()
    private static let pendingName = "identity-restore.pending"
    private static func digest(_ bytes: Data) -> String {
        Data(SHA256.hash(data: bytes)).map { String(format: "%02x", $0) }.joined()
    }
    static func support() throws -> URL {
        try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                   appropriateFor: nil, create: true)
    }
    static func importFile(_ url: URL) throws -> Key {
        let file = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard file >= 0 else { throw Failure.unavailable }
        defer { Darwin.close(file) }
        return try Key(read(file, maximum: 64, privateFile: false))
    }
    static func status(support: URL) throws -> Status {
        lock.lock(); defer { lock.unlock() }
        let root = try Directory(support)
        let current = try Self.current(root)
        var pendingKey: Key? = nil
        var pendingError: String? = nil
        do { pendingKey = try Self.pending(root).map { try Key(Data(base64Encoded: $0.privateKey) ?? Data()) } }
        catch { pendingError = "The pending restore is invalid. Cancel it or choose the identity file again." }
        var saved: [Key] = []
        var savedError: String? = nil
        do {
            if let folder = try root.child("identity-backups", create: false) {
                for name in try FileManager.default.contentsOfDirectory(atPath: folder.url.path).sorted() {
                    guard name.range(of: "^[a-f0-9]{32}\\.identity$", options: .regularExpression) != nil else { continue }
                    do {
                        guard saved.count < 64, let bytes = try folder.read(name, maximum: 64) else { throw Failure.savedCopy }
                        let key = try Key(bytes)
                        guard name == key.hash + ".identity" else { throw Failure.savedCopy }
                        if key.hash != current?.hash { saved.append(key) }
                    } catch { savedError = "Some previous identities could not be verified. Their files have been kept unchanged." }
                }
            }
        } catch { savedError = "Previous identities could not be opened safely. Their files have been kept unchanged." }
        return Status(current: current, pending: pendingKey, saved: saved,
                      pendingError: pendingError, savedError: savedError)
    }

    /// Return false for the already-active identity, without requiring restart.
    @discardableResult static func stage(_ key: Key, support: URL) throws -> Bool {
        lock.lock(); defer { lock.unlock() }
        let root = try Directory(support), original = try Self.current(root)
        if original?.hash == key.hash {
            try root.remove(pendingName)
            return false
        }
        let value = Pending(version: 1, originalDigest: original.map { digest($0.bytes) },
                            replacementHash: key.hash, privateKey: key.bytes.base64EncodedString())
        try root.write(pendingName, bytes: JSONEncoder().encode(value))
        return true
    }
    static func cancel(support: URL) throws {
        lock.lock(); defer { lock.unlock() }
        try Directory(support).remove(pendingName)
    }
    /// Only the cold-start owner calls this, before starting the interpreter.
    /// The previous private key is durably retained before an atomic replacement.
    static func applyPending(support: URL) throws {
        lock.lock(); defer { lock.unlock() }
        let root = try Directory(support)
        guard let value = try Self.pending(root), let bytes = Data(base64Encoded: value.privateKey) else { return }
        let replacement = try Key(bytes), original = try Self.current(root)
        if original?.hash == replacement.hash {
            try root.remove(pendingName)
            return
        }
        guard original.map({ digest($0.bytes) }) == value.originalDigest else { throw Failure.changed }
        if let original {
            let backups = try root.child("identity-backups", create: true)!
            let name = original.hash + ".identity"
            if let saved = try backups.read(name, maximum: 64) {
                guard saved == original.bytes else { throw Failure.savedCopy }
            } else {
                let count = try FileManager.default.contentsOfDirectory(atPath: backups.url.path)
                    .filter { $0.hasSuffix(".identity") }.count
                guard count < 64 else { throw Failure.savedCopy }
                try backups.write(name, bytes: original.bytes)
                guard try backups.read(name, maximum: 64) == original.bytes else { throw Failure.savedCopy }
            }
        }
        let folder = try root.child(identityDirectoryName, create: true)!
        try folder.write("identity", bytes: replacement.bytes)
        guard try Self.current(root)?.bytes == replacement.bytes else { throw Failure.unavailable }
        try root.remove(pendingName)
    }
    private static func current(_ root: Directory) throws -> Key? {
        guard let folder = try root.child(identityDirectoryName, create: false),
              let bytes = try folder.read("identity", maximum: 64) else { return nil }
        return try Key(bytes)
    }
    private static func pending(_ root: Directory) throws -> Pending? {
        guard let bytes = try root.read(pendingName, maximum: 2048) else { return nil }
        guard let object = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              Set(object.keys).isSubset(of: ["version", "originalDigest", "replacementHash", "privateKey"]),
              let value = try? JSONDecoder().decode(Pending.self, from: bytes), value.version == 1,
              value.originalDigest == nil || value.originalDigest?.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              let raw = Data(base64Encoded: value.privateKey), let key = try? Key(raw),
              key.hash == value.replacementHash else { throw Failure.invalidPending }
        return value
    }
    private static func read(_ file: Int32, maximum: Int, privateFile: Bool) throws -> Data {
        var info = stat()
        guard fstat(file, &info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              info.st_size >= 0, info.st_size <= off_t(maximum),
              !privateFile || (info.st_uid == getuid() && (info.st_mode & 0o077) == 0) else { throw Failure.unavailable }
        var bytes = [UInt8](repeating: 0, count: maximum + 1), count = 0
        while count < bytes.count {
            let received = bytes.withUnsafeMutableBytes { buffer in
                Darwin.read(file, buffer.baseAddress!.advanced(by: count), buffer.count - count)
            }
            if received == 0 { break }
            if received < 0 { if errno == EINTR { continue }; throw Failure.unavailable }
            count += received
        }
        guard count <= maximum else { throw Failure.unavailable }
        return Data(bytes.prefix(count))
    }
    private final class Directory {
        let descriptor: Int32
        let url: URL
        init(_ url: URL) throws {
            self.url = url
            descriptor = Darwin.open(url.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard descriptor >= 0 else { throw Failure.unavailable }
        }
        private init(_ descriptor: Int32, url: URL) { self.descriptor = descriptor; self.url = url }
        deinit { Darwin.close(descriptor) }
        func child(_ name: String, create: Bool) throws -> Directory? {
            if create && mkdirat(descriptor, name, 0o700) != 0 && errno != EEXIST { throw Failure.unavailable }
            let child = openat(descriptor, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            if child < 0 { if !create && errno == ENOENT { return nil }; throw Failure.unavailable }
            return Directory(child, url: url.appendingPathComponent(name, isDirectory: true))
        }
        func read(_ name: String, maximum: Int) throws -> Data? {
            let file = openat(descriptor, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            if file < 0 { if errno == ENOENT { return nil }; throw Failure.unavailable }
            defer { Darwin.close(file) }
            return try NextIdentityRecovery.read(file, maximum: maximum, privateFile: true)
        }
        func remove(_ name: String) throws {
            if unlinkat(descriptor, name, 0) != 0 && errno != ENOENT { throw Failure.unavailable }
            guard fsync(descriptor) == 0 else { throw Failure.unavailable }
        }
        func write(_ name: String, bytes: Data) throws {
            let temporary = ".identity-" + UUID().uuidString
            let file = openat(descriptor, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
            guard file >= 0 else { throw Failure.unavailable }
            defer { Darwin.close(file); unlinkat(descriptor, temporary, 0) }
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                                                  ofItemAtPath: url.appendingPathComponent(temporary).path)
            try bytes.withUnsafeBytes { buffer in
                var offset = 0
                while offset < buffer.count {
                    let written = Darwin.write(file, buffer.baseAddress!.advanced(by: offset), buffer.count - offset)
                    if written < 0 { if errno == EINTR { continue }; throw Failure.unavailable }
                    guard written > 0 else { throw Failure.unavailable }
                    offset += written
                }
            }
            guard fsync(file) == 0, renameat(descriptor, temporary, descriptor, name) == 0,
                  fsync(descriptor) == 0 else { throw Failure.unavailable }
        }
    }
}
