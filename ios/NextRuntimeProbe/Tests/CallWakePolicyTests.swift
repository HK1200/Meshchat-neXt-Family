// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

final class CallWakePolicyTests: XCTestCase {
    private func sample() throws -> (NextCallWakePolicy, [String: Any]) {
        let key = Curve25519.KeyAgreement.PrivateKey().publicKey.rawRepresentation + Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        let voice = try FamilyCallWake.voiceAddress(publicKey: key)
        let address = try NextCallWakeIdentity.messagingAddress(publicKey: key)
        let hex = key.map { String(format: "%02x", $0) }.joined()
        let json: [String: Any] = ["address": address, "voiceAddress": voice, "identityPublicKey": hex,
            "enabled": true, "policyDigest": String(repeating: "a", count: 64),
            "contacts": [["name": "Approved", "identityPublicKey": hex, "addresses": ["voice": voice, "lxmf": address]]]]
        return (try JSONDecoder().decode(NextCallWakePolicy.self, from: JSONSerialization.data(withJSONObject: json)), json)
    }
    private func decode(_ json: [String: Any]) throws -> NextCallWakePolicy {
        try JSONDecoder().decode(NextCallWakePolicy.self, from: JSONSerialization.data(withJSONObject: json))
    }
    func testSelectionRequiresTheBoundPublicMessagingAndVoiceIdentity() throws {
        let (policy, _) = try sample()
        let selected = try policy.callers(selected: [policy.voiceAddress])
        XCTAssertEqual(selected.count, 1); XCTAssertEqual(selected.first?.name, "Approved")
        XCTAssertEqual(try FamilyCallWake.voiceAddress(publicKey: XCTUnwrap(selected.first?.publicKey)), policy.voiceAddress)
    }
    func testMissingUnselectedOrDuplicateContactCannotBecomeConsent() throws {
        let (policy, original) = try sample()
        XCTAssertThrowsError(try policy.callers(selected: []))
        XCTAssertThrowsError(try policy.callers(selected: [String(repeating: "0", count: 32)]))
        var duplicate = original
        let rows = try XCTUnwrap(original["contacts"] as? [[String: Any]])
        duplicate["contacts"] = rows + rows
        XCTAssertThrowsError(try decode(duplicate).callers(selected: [policy.voiceAddress]))
    }
    func testFalseCallingPolicyAndMalformedDigestFailClosed() throws {
        let (policy, original) = try sample()
        var disabled = original; disabled["enabled"] = false
        XCTAssertThrowsError(try decode(disabled).callers(selected: [policy.voiceAddress]))
        var badDigest = original; badDigest["policyDigest"] = String(repeating: "a", count: 64) + "\n"
        XCTAssertThrowsError(try decode(badDigest).callers(selected: [policy.voiceAddress]))
    }
    func testAnAnnounceKeyBoundToAnotherContactCannotBeSelected() throws {
        let (policy, original) = try sample()
        var json = original
        var rows = try XCTUnwrap(original["contacts"] as? [[String: Any]])
        let other = Curve25519.KeyAgreement.PrivateKey().publicKey.rawRepresentation + Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        rows[0]["identityPublicKey"] = other.map { String(format: "%02x", $0) }.joined()
        json["contacts"] = rows
        XCTAssertThrowsError(try decode(json).callers(selected: [policy.voiceAddress]))
    }
    func testPublicMetadataCannotLoadAPrivateIdentityFromItsOwnFields() throws {
        let (policy, _) = try sample()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("missing-private-key-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertThrowsError(try policy.ownIdentity(support: root))
        XCTAssertThrowsError(try NextCallWakePolicy.publicKey(String(repeating: "a", count: 128) + "\n"))
    }
}
