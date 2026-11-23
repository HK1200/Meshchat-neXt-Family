// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

final class CallWakeCancellationTests: XCTestCase {
    private func sample(domain: String = "neXt Reticulum call cancel v1\0", issued: Int = 1000) throws -> (FamilyCallWake, [String: Any]) {
        let signing = Curve25519.Signing.PrivateKey()
        let publicKey = Curve25519.KeyAgreement.PrivateKey().publicKey.rawRepresentation + signing.publicKey.rawRepresentation
        let sender = publicKey.map { String(format: "%02x", $0) }.joined()
        let call = UUID(), recipient = String(repeating: "a", count: 32)
        let wake = FamilyCallWake(recipient: recipient, call: call, sender: sender,
            callerVoice: try FamilyCallWake.voiceAddress(publicKey: publicKey), issued: 1000)
        var hint: [String: Any] = ["recipient": recipient,
            "call": call.uuidString.lowercased().replacingOccurrences(of: "-", with: ""),
            "sender": sender, "issued": issued]
        var canonical = hint; canonical["audience"] = "private-calls"
        let bytes = try JSONSerialization.data(withJSONObject: canonical, options: [.sortedKeys, .withoutEscapingSlashes])
        hint["signature"] = try signing.signature(for: Data(domain.utf8) + bytes).map { String(format: "%02x", $0) }.joined()
        return (wake, ["state": "cancelled", "hint": hint])
    }
    private func check(_ reply: [String: Any], wake: FamilyCallWake, audience: String = "private-calls", now: Int = 1000) throws -> Bool {
        NextCallWakeCancellation.verified(try JSONSerialization.data(withJSONObject: reply), wake: wake, audience: audience, now: now)
    }
    func testPythonProviderCancellationVerifiesAgainstItsActualSealedWake() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let vectors = try XCTUnwrap(fixture["vectors"] as? [String: Any])
        let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: Data((0..<32).map(UInt8.init)))
        let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: Data((32..<64).map(UInt8.init)))
        let publicKey = agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation
        let payload = try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors["valid"]))
        let wake = try FamilyCallWake.decode(payload, recipientPrivateKey: agreement.rawRepresentation,
            recipientPublicKey: publicKey, audience: "private-calls",
            approvedCallers: [try XCTUnwrap(fixture["caller"] as? String)], now: 1000)
        let response = try JSONSerialization.data(withJSONObject: XCTUnwrap(fixture["cancelState"]))
        XCTAssertTrue(NextCallWakeCancellation.verified(response, wake: wake, audience: "private-calls", now: 1000))
    }

    func testOriginalCallerCanCancelOnlyItsPendingIntent() throws {
        let (wake, reply) = try sample()
        XCTAssertTrue(try check(reply, wake: wake))
    }
    func testAValidWakeSignatureCannotBeReusedAsCancellation() throws {
        let (wake, reply) = try sample(domain: "neXt Reticulum call wake v1\0")
        XCTAssertFalse(try check(reply, wake: wake))
    }
    func testProviderStateWithoutAValidSignatureCannotEndTheCall() throws {
        let (wake, original) = try sample()
        for field in ["signature", "recipient", "call", "sender"] {
            var reply = original, hint = try XCTUnwrap(original["hint"] as? [String: Any])
            hint[field] = String(repeating: "0", count: field == "signature" || field == "sender" ? 128 : 32)
            reply["hint"] = hint
            XCTAssertFalse(try check(reply, wake: wake), field)
        }
    }
    func testWrongAudienceExpiredFutureAndPreWakeCancellationAreRejected() throws {
        let (wake, reply) = try sample()
        XCTAssertFalse(try check(reply, wake: wake, audience: "other-provider"))
        XCTAssertFalse(try check(reply, wake: wake, audience: "private-calls\n"))
        XCTAssertFalse(try check(reply, wake: wake, now: 1031))
        XCTAssertFalse(try check(reply, wake: wake, now: 989))
        let (oldWake, oldReply) = try sample(issued: 999)
        XCTAssertFalse(try check(oldReply, wake: oldWake))
    }
    func testExtraFieldsBooleanTimeAndUnrelatedStatesAreRejected() throws {
        let (wake, original) = try sample()
        var extra = original; extra["unexpected"] = "ignore"
        XCTAssertFalse(try check(extra, wake: wake))
        var boolean = original, hint = try XCTUnwrap(original["hint"] as? [String: Any])
        hint["issued"] = true; boolean["hint"] = hint
        XCTAssertFalse(try check(boolean, wake: wake))
        for state in ["ringing", "expired", "unknown"] {
            var reply = original; reply["state"] = state
            XCTAssertFalse(try check(reply, wake: wake))
        }
        XCTAssertFalse(NextCallWakeCancellation.verified(Data(repeating: 0, count: 2305), wake: wake, audience: "private-calls", now: 1000))
    }
}
