// SPDX-License-Identifier: 0BSD
import CryptoKit
import Darwin
import Foundation

/// Native-only decryption material. It is deliberately not Codable and never
/// passes through the web bridge or the public enrollment metadata endpoint.
struct NextCallWakeIdentity {
    let agreementPrivateKey: Data
    let publicKey: Data
    let address: String
    let voiceAddress: String
    enum Invalid: Error { case unavailable, binding }

    static func decode(_ raw: Data, expectedPublicKey: Data,
                       address: String, voiceAddress: String) throws -> Self {
        guard raw.count == 64, expectedPublicKey.count == 64,
              address.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              voiceAddress.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { throw Invalid.binding }
        let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: raw.prefix(32))
        let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: raw.suffix(32))
        let publicKey = agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation
        guard publicKey == expectedPublicKey,
              destination("lxmf.delivery", publicKey) == address,
              try FamilyCallWake.voiceAddress(publicKey: publicKey) == voiceAddress else { throw Invalid.binding }
        return Self(agreementPrivateKey: agreement.rawRepresentation, publicKey: publicKey,
                    address: address, voiceAddress: voiceAddress)
    }

    /// The base must come from this app's Application Support directory. The
    /// two fixed descendants are opened relative to directory descriptors,
    /// without following imported/replaced radio-folder or key-file symlinks.
    static func load(support: URL, expectedPublicKey: Data,
                     address: String, voiceAddress: String) throws -> Self {
        let base = Darwin.open(support.path, O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        guard base >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(base) }
        let folder = openat(base, "reticulum", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard folder >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(folder) }
        let file = openat(folder, "identity", O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        guard file >= 0 else { throw Invalid.unavailable }
        defer { Darwin.close(file) }
        var info = stat()
        guard fstat(file, &info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              info.st_uid == getuid(), info.st_size == 64, (info.st_mode & 0o077) == 0 else { throw Invalid.unavailable }
        var bytes = [UInt8](repeating: 0, count: 65), count = 0
        while count < bytes.count {
            let readCount = bytes.withUnsafeMutableBytes { buffer in
                Darwin.read(file, buffer.baseAddress!.advanced(by: count), buffer.count - count)
            }
            if readCount == 0 { break }
            if readCount < 0 {
                if errno == EINTR { continue }
                throw Invalid.unavailable
            }
            count += readCount
        }
        guard count == 64 else { throw Invalid.unavailable }
        return try decode(Data(bytes.prefix(count)), expectedPublicKey: expectedPublicKey,
                          address: address, voiceAddress: voiceAddress)
    }

    private static func destination(_ aspect: String, _ publicKey: Data) -> String {
        let name = Data(SHA256.hash(data: Data(aspect.utf8)).prefix(10))
        let identity = Data(SHA256.hash(data: publicKey).prefix(16))
        return Data(SHA256.hash(data: name + identity).prefix(16)).map { String(format: "%02x", $0) }.joined()
    }
}
