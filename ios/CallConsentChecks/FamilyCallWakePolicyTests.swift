// SPDX-License-Identifier: 0BSD
import CryptoKit
import Darwin
import Foundation
import XCTest

final class FamilyCallWakePolicyTests: XCTestCase {
    private let own = Data((0..<64).map(UInt8.init))
    private func publicKey(_ raw: Data) throws -> Data {
        try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: raw.prefix(32)).publicKey.rawRepresentation +
            Curve25519.Signing.PrivateKey(rawRepresentation: raw.suffix(32)).publicKey.rawRepresentation
    }
    private func sample() throws -> ([String: Any], String) {
        let key = try publicKey(Data((64..<128).map(UInt8.init)))
        let voice = try FamilyCallWake.voiceAddress(publicKey: key)
        let contact: [String: Any] = ["id": 7, "name": "Approved radio", "identityPublicKey": key.map { String(format: "%02x", $0) }.joined(),
            "addresses": ["lxmf": FamilyCallWakePolicy.messagingAddress(key), "lxst": voice]]
        return (["setup_complete": true, "voiceEnabled": true, "contacts": [contact]], voice)
    }
    private func bytes(_ json: [String: Any]) throws -> Data { try JSONSerialization.data(withJSONObject: json) }
    private func approval(_ json: [String: Any], _ selected: Set<String>) throws -> FamilyCallWakePolicy.Approval {
        try FamilyCallWakePolicy.decode(bytes(json)).approval(selected: selected, recipientPublicKey: publicKey(own))
    }
    private func directory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("family-approval-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("FamilyTCP"), withIntermediateDirectories: true)
        return root
    }
    private func write(_ data: Data, _ name: String, at root: URL) throws {
        let url = root.appendingPathComponent("FamilyTCP/" + name)
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
    func testOnlyExplicitlySelectedApprovedPrivateContactsGrantAccess() throws {
        let (state, voice) = try sample()
        let approved = try approval(state, [voice])
        XCTAssertEqual(approved.callers.count, 1)
        XCTAssertEqual(approved.callers.first?.name, "Approved radio")
        XCTAssertEqual(approved.digest.count, 64)
        XCTAssertThrowsError(try approval(state, []))
        XCTAssertThrowsError(try approval(state, [String(repeating: "a", count: 32)]))
    }
    func testSetupAndVoicePermissionAreBothRequired() throws {
        let (state, voice) = try sample()
        for name in ["setup_complete", "voiceEnabled"] {
            var changed = state; changed[name] = false
            XCTAssertThrowsError(try approval(changed, [voice]))
            changed.removeValue(forKey: name)
            XCTAssertThrowsError(try approval(changed, [voice]))
        }
    }
    func testMessagingAndVoiceAddressesMustBothBelongToTheSavedPublicKey() throws {
        let (state, voice) = try sample()
        for service in ["lxmf", "lxst"] {
            var changed = state
            var rows = try XCTUnwrap(state["contacts"] as? [[String: Any]])
            var addresses = try XCTUnwrap(rows[0]["addresses"] as? [String: String])
            addresses[service] = String(repeating: "0", count: 32)
            rows[0]["addresses"] = addresses; changed["contacts"] = rows
            XCTAssertThrowsError(try approval(changed, [voice]))
        }
    }
    func testDuplicateContactBindingsCannotGrantAmbiguousConsent() throws {
        var (state, voice) = try sample()
        let rows = try XCTUnwrap(state["contacts"] as? [[String: Any]])
        state["contacts"] = rows + rows
        XCTAssertThrowsError(try approval(state, [voice]))
    }
    func testAnnouncesAndRoomLabelsNeverCreatePrivateApprovals() throws {
        var (state, voice) = try sample()
        state["announces"] = state["contacts"]
        state["roomNames"] = state["contacts"]
        state["contacts"] = []
        XCTAssertThrowsError(try approval(state, [voice]))
    }
    func testMessagesMapsPhotosAndNetworkChangesDoNotChangeApprovalDigest() throws {
        let (state, voice) = try sample()
        let before = try approval(state, [voice])
        var changed = state
        changed["messages"] = [["text": "private text"]]
        changed["peer"] = ["host": "example.invalid", "port": 4343]
        changed["locations"] = ["latitude": 48]
        var rows = try XCTUnwrap(state["contacts"] as? [[String: Any]])
        rows[0]["photo"] = "private image"; changed["contacts"] = rows
        XCTAssertEqual(try approval(changed, [voice]), before)
    }
    func testSelectedContactRenameChangesDigestAndRemovalRevokesApproval() throws {
        let (state, voice) = try sample(); let before = try approval(state, [voice])
        var changed = state
        var rows = try XCTUnwrap(state["contacts"] as? [[String: Any]])
        rows[0]["name"] = "New label"; changed["contacts"] = rows
        XCTAssertNotEqual(try approval(changed, [voice]).digest, before.digest)
        changed["contacts"] = []
        XCTAssertThrowsError(try approval(changed, [voice]))
    }
    func testMalformedKeyAndControlCharactersCannotEnterEnrollment() throws {
        let (state, voice) = try sample()
        for edit in [["identityPublicKey": String(repeating: "a", count: 128) + "\n"], ["name": "Bad\nname"], ["name": String(repeating: "x", count: 257)]] {
            var changed = state
            var rows = try XCTUnwrap(state["contacts"] as? [[String: Any]])
            for (key, value) in edit { rows[0][key] = value }
            changed["contacts"] = rows
            XCTAssertThrowsError(try approval(changed, [voice]))
        }
    }
    func testColdReadUsesOnlyThisAppsExistingIdentityAndApprovals() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let (state, voice) = try sample()
        try write(bytes(state), "state.json", at: root); try write(own, "identity", at: root)
        XCTAssertEqual(try FamilyCallWakePolicy.load(support: root).approval(selected: [voice], recipientPublicKey: publicKey(own)), try approval(state, [voice]))
        XCTAssertEqual(try FamilyCallWakePolicy.identity(support: root, expectedPublicKey: publicKey(own)), own.prefix(32))
        XCTAssertThrowsError(try FamilyCallWakePolicy.identity(support: root, expectedPublicKey: Data(repeating: 0, count: 64)))
    }
    func testSymlinksCannotRedirectStateIdentityOrTheirFolder() throws {
        let root = try directory(), outside = try directory()
        defer { try? FileManager.default.removeItem(at: root); try? FileManager.default.removeItem(at: outside) }
        let (state, _) = try sample(); try write(bytes(state), "state.json", at: outside); try write(own, "identity", at: outside)
        for name in ["state.json", "identity"] {
            try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("FamilyTCP/" + name), withDestinationURL: outside.appendingPathComponent("FamilyTCP/" + name))
        }
        XCTAssertThrowsError(try FamilyCallWakePolicy.load(support: root))
        XCTAssertThrowsError(try FamilyCallWakePolicy.identity(support: root, expectedPublicKey: publicKey(own)))
        try FileManager.default.removeItem(at: root.appendingPathComponent("FamilyTCP"))
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("FamilyTCP"), withDestinationURL: outside.appendingPathComponent("FamilyTCP"))
        XCTAssertThrowsError(try FamilyCallWakePolicy.load(support: root))
    }
    func testPublicFilesNamedPipesAndTruncatedKeysFailWithoutBlocking() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let (state, _) = try sample(); try write(bytes(state), "state.json", at: root)
        let path = root.appendingPathComponent("FamilyTCP/state.json")
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: path.path)
        XCTAssertThrowsError(try FamilyCallWakePolicy.load(support: root))
        try FileManager.default.removeItem(at: path)
        XCTAssertEqual(mkfifo(path.path, 0o600), 0)
        XCTAssertThrowsError(try FamilyCallWakePolicy.load(support: root))
        for size in [0, 32, 63, 65] {
            try write(Data(repeating: 1, count: size), "identity", at: root)
            XCTAssertThrowsError(try FamilyCallWakePolicy.identity(support: root, expectedPublicKey: publicKey(own)))
        }
    }
    func testAtomicSavedPermissionReplacementIsRecheckedOnEveryLoad() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        var (state, voice) = try sample(); try write(bytes(state), "state.json", at: root)
        XCTAssertNoThrow(try FamilyCallWakePolicy.load(support: root).approval(selected: [voice], recipientPublicKey: publicKey(own)))
        state["voiceEnabled"] = false; try write(bytes(state), "state.json", at: root)
        XCTAssertThrowsError(try FamilyCallWakePolicy.load(support: root).approval(selected: [voice], recipientPublicKey: publicKey(own)))
        try write(Data("{".utf8), "state.json", at: root)
        XCTAssertThrowsError(try FamilyCallWakePolicy.load(support: root))
    }
    private func fixturePayload(_ vector: String = "valid") throws -> Data {
        let path = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: path)) as? [String: Any])
        let vectors = try XCTUnwrap(json["vectors"] as? [String: Any])
        return try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors[vector]))
    }
    func testRealPythonProviderIntentUsesOnlyTheCurrentSelectedGuardianContact() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let (state, voice) = try sample(); let allowed = try approval(state, [voice])
        try write(bytes(state), "state.json", at: root); try write(own, "identity", at: root)
        let admitted = try FamilyCallWakePolicy.admit(fixturePayload(), support: root,
            recipientPublicKey: publicKey(own), audience: "private-calls", selected: [voice],
            approvalDigest: allowed.digest, now: 1000)
        XCTAssertEqual(admitted.wake.callerVoice, voice)
        XCTAssertEqual(admitted.name, "Approved radio")
        XCTAssertEqual(admitted.approvalDigest, allowed.digest)
    }
    func testColdSavedConsentCannotOverrideARevokedOrRenamedContact() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let (state, voice) = try sample(); let allowed = try approval(state, [voice])
        try write(own, "identity", at: root)
        var changed = state
        var rows = try XCTUnwrap(state["contacts"] as? [[String: Any]])
        rows[0]["name"] = "Changed by guardian"; changed["contacts"] = rows
        try write(bytes(changed), "state.json", at: root)
        XCTAssertThrowsError(try FamilyCallWakePolicy.admit(fixturePayload(), support: root,
            recipientPublicKey: publicKey(own), audience: "private-calls", selected: [voice],
            approvalDigest: allowed.digest, now: 1000))
        changed["contacts"] = []; try write(bytes(changed), "state.json", at: root)
        XCTAssertThrowsError(try FamilyCallWakePolicy.admit(fixturePayload(), support: root,
            recipientPublicKey: publicKey(own), audience: "private-calls", selected: [voice],
            approvalDigest: allowed.digest, now: 1000))
    }
    func testAdmissionRejectsExpiredAndWrongAudienceProviderIntents() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let (state, voice) = try sample(); let allowed = try approval(state, [voice])
        try write(bytes(state), "state.json", at: root); try write(own, "identity", at: root)
        XCTAssertThrowsError(try FamilyCallWakePolicy.admit(fixturePayload(), support: root,
            recipientPublicKey: publicKey(own), audience: "other-provider", selected: [voice],
            approvalDigest: allowed.digest, now: 1000))
        XCTAssertThrowsError(try FamilyCallWakePolicy.admit(fixturePayload(), support: root,
            recipientPublicKey: publicKey(own), audience: "private-calls", selected: [voice],
            approvalDigest: allowed.digest, now: 1100))
    }
    func testGuardianDisablingVoiceRejectsAnOtherwiseValidProviderIntent() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        var (state, voice) = try sample(); let allowed = try approval(state, [voice])
        state["voiceEnabled"] = false
        try write(bytes(state), "state.json", at: root); try write(own, "identity", at: root)
        XCTAssertThrowsError(try FamilyCallWakePolicy.admit(fixturePayload(), support: root,
            recipientPublicKey: publicKey(own), audience: "private-calls", selected: [voice],
            approvalDigest: allowed.digest, now: 1000))
    }

}
