// SPDX-License-Identifier: 0BSD
import Foundation
import Darwin
import XCTest

@MainActor final class CallWakeIdentityTests: XCTestCase {
    private func fixture() throws -> [String: Any] {
        let path = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: path)) as? [String: Any])
    }
    private func values() throws -> (Data, String, String) {
        let f = try fixture(), hex = try XCTUnwrap(f["recipientPublicKey"] as? String)
        var publicKey = Data()
        for offset in stride(from: 0, to: hex.count, by: 2) {
            let start = hex.index(hex.startIndex, offsetBy: offset), end = hex.index(start, offsetBy: 2)
            publicKey.append(try XCTUnwrap(UInt8(hex[start..<end], radix: 16)))
        }
        return (publicKey, try XCTUnwrap(f["recipientMessaging"] as? String), try XCTUnwrap(f["recipient"] as? String))
    }
    private func directory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("native-identity-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("reticulum"), withIntermediateDirectories: true)
        return root
    }
    private func key(_ raw: Data, at root: URL) throws {
        let path = root.appendingPathComponent("reticulum/identity")
        try raw.write(to: path)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
    private func load(_ root: URL) throws -> NextCallWakeIdentity {
        let (publicKey, address, voice) = try values()
        return try NextCallWakeIdentity.load(support: root, expectedPublicKey: publicKey, address: address, voiceAddress: voice)
    }
    func testRealReticulumFileDerivesBoundPublicAddressesAndDecryptsThePythonFixture() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        try key(Data((0..<64).map(UInt8.init)), at: root)
        let identity = try load(root), f = try fixture()
        XCTAssertEqual(identity.agreementPrivateKey.count, 32)
        let vectors = try XCTUnwrap(f["vectors"] as? [String: Any])
        let payload = try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors["valid"]))
        let caller = try XCTUnwrap(f["caller"] as? String)
        let wake = try FamilyCallWake.decode(payload, recipientPrivateKey: identity.agreementPrivateKey,
            recipientPublicKey: identity.publicKey, audience: "private-calls", approvedCallers: [caller], now: 1000)
        XCTAssertEqual(wake.callerVoice, caller); XCTAssertEqual(wake.recipient, identity.voiceAddress)
    }
    func testPublicKeyMessagingAndVoiceBindingsAreAllRequired() throws {
        let (publicKey, address, voice) = try values(), raw = Data((0..<64).map(UInt8.init))
        XCTAssertThrowsError(try NextCallWakeIdentity.decode(raw, expectedPublicKey: Data(repeating: 0, count: 64), address: address, voiceAddress: voice))
        XCTAssertThrowsError(try NextCallWakeIdentity.decode(raw, expectedPublicKey: publicKey, address: String(repeating: "a1", count: 16), voiceAddress: voice))
        XCTAssertThrowsError(try NextCallWakeIdentity.decode(raw, expectedPublicKey: publicKey, address: address, voiceAddress: String(repeating: "b2", count: 16)))
        XCTAssertThrowsError(try NextCallWakeIdentity.decode(Data(raw.prefix(32)), expectedPublicKey: publicKey, address: address, voiceAddress: voice))
    }
    func testMissingMalformedAndOversizedFilesDoNotProduceEnrollmentKeys() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertThrowsError(try load(root))
        for size in [0, 32, 63, 65, 4096] {
            try key(Data(repeating: 1, count: size), at: root)
            XCTAssertThrowsError(try load(root))
        }
    }
    func testKeyAndReticulumFolderSymlinksCannotEscapeTheAnchoredDirectory() throws {
        let root = try directory(), outside = try directory()
        defer { try? FileManager.default.removeItem(at: root); try? FileManager.default.removeItem(at: outside) }
        try key(Data((0..<64).map(UInt8.init)), at: outside)
        let file = root.appendingPathComponent("reticulum/identity")
        try FileManager.default.createSymbolicLink(at: file, withDestinationURL: outside.appendingPathComponent("reticulum/identity"))
        XCTAssertThrowsError(try load(root))
        try FileManager.default.removeItem(at: root.appendingPathComponent("reticulum"))
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("reticulum"), withDestinationURL: outside.appendingPathComponent("reticulum"))
        XCTAssertThrowsError(try load(root))
        XCTAssertNoThrow(try load(outside))
    }
    func testPubliclyReadableIdentityFileCannotBeCopiedIntoCallEnrollment() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        try key(Data((0..<64).map(UInt8.init)), at: root)
        let file = root.appendingPathComponent("reticulum/identity")
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file.path)
        XCTAssertThrowsError(try load(root))
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        XCTAssertNoThrow(try load(root))
    }
    func testDirectoriesAndNamedPipesAreRejectedWithoutBlockingTheMainActor() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let path = root.appendingPathComponent("reticulum/identity")
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: false)
        XCTAssertThrowsError(try load(root))
        try FileManager.default.removeItem(at: path)
        XCTAssertEqual(mkfifo(path.path, 0o600), 0)
        XCTAssertThrowsError(try load(root))
    }

}
