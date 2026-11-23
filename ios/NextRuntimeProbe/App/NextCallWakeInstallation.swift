// SPDX-License-Identifier: 0BSD
import Darwin
import Foundation
import Security

/// The Keychain can survive app removal. Consent cannot: a new app container
/// lacks this random marker and must obtain explicit enrollment again.
struct NextCallWakeInstallation {
    private static let name = ".next-call-alert-installation-v1"
    enum Invalid: Error { case unavailable }

    static func read(support: URL) throws -> Data? {
        let directory = Darwin.open(support.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard directory >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(directory) }
        let file = openat(directory, name, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        if file < 0 && errno == ENOENT { return nil }
        guard file >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(file) }
        var info = stat()
        guard fstat(file, &info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              info.st_uid == getuid(), info.st_size == 32, (info.st_mode & 0o077) == 0 else { throw Invalid.unavailable }
        var bytes = [UInt8](repeating: 0, count: 33), count = 0
        while count < bytes.count {
            let result = bytes.withUnsafeMutableBytes { buffer in
                Darwin.read(file, buffer.baseAddress!.advanced(by: count), buffer.count - count)
            }
            if result == 0 { break }
            if result < 0 {
                if errno == EINTR { continue }
                throw Invalid.unavailable
            }
            count += result
        }
        guard count == 32 else { throw Invalid.unavailable }
        return Data(bytes.prefix(count))
    }

    /// Remove only this app's reserved marker. unlinkat never follows a
    /// replacement symlink, so its destination and all other files survive.
    static func invalidate(support: URL) throws {
        let directory = Darwin.open(support.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard directory >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(directory) }
        if unlinkat(directory, name, 0) != 0 && errno != ENOENT { throw Invalid.unavailable }
    }

    /// Only call from explicit foreground opt-in, never from cold-start load.
    static func createForOptIn(support: URL) throws -> Data {
        if let existing = try read(support: support) { return existing }
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw Invalid.unavailable }
        let directory = Darwin.open(support.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard directory >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(directory) }
        let file = openat(directory, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        if file < 0 && errno == EEXIST {
            guard let existing = try read(support: support) else { throw Invalid.unavailable }
            return existing
        }
        guard file >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(file) }
        var count = 0
        while count < bytes.count {
            let result = bytes.withUnsafeBytes { buffer in
                Darwin.write(file, buffer.baseAddress!.advanced(by: count), buffer.count - count)
            }
            if result < 0 && errno == EINTR { continue }
            guard result > 0 else { throw Invalid.unavailable }
            count += result
        }
        guard fsync(file) == 0 else { throw Invalid.unavailable }
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: support.appendingPathComponent(name).path)
        let result = Data(bytes)
        guard try read(support: support) == result else { throw Invalid.unavailable }
        return result
    }
}
