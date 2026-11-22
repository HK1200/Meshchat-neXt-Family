import CryptoKit
import Foundation
import XCTest

final class CallWakeTests: XCTestCase {
    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }
    private func publicKey() throws -> Data {
        // Public, deterministic, test-only identity: private bytes 0 through 63.
        let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: Data((0..<32).map(UInt8.init)))
        let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: Data((32..<64).map(UInt8.init)))
        return agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation
    }
    private func payload(_ name: String) throws -> Data {
        let vectors = try XCTUnwrap(fixture()["vectors"] as? [String: Any])
        return try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors[name]))
    }
    private func decode(_ data: Data, audience: String = "private-calls", approved: Bool = true,
                        privateKey: Data? = nil) throws -> FamilyCallWake {
        let caller = try XCTUnwrap(fixture()["caller"] as? String)
        return try FamilyCallWake.decode(data,
            recipientPrivateKey: privateKey ?? Data((0..<32).map(UInt8.init)), recipientPublicKey: publicKey(),
            audience: audience, approvedCallers: approved ? [caller] : [], now: 1000)
    }

    func testPythonProviderPayloadDecryptsAndVerifiesStandardReticulumIdentity() throws {
        let value = try decode(payload("valid"))
        XCTAssertEqual(value.recipient, try XCTUnwrap(fixture()["recipient"] as? String))
        XCTAssertEqual(value.callerVoice, try XCTUnwrap(fixture()["caller"] as? String))
        XCTAssertEqual(value.issued, 1000)
        XCTAssertEqual(value.call.uuidString.lowercased().replacingOccurrences(of: "-", with: ""), String(repeating: "03", count: 16))
        XCTAssertEqual(try FamilyCallWake.voiceAddress(publicKey: publicKey()), value.recipient)
    }
    func testWrongIdentityAudienceAndUnapprovedCallerCannotRing() throws {
        XCTAssertThrowsError(try decode(payload("valid"), audience: "another-provider"))
        XCTAssertThrowsError(try decode(payload("valid"), approved: false))
        XCTAssertThrowsError(try decode(payload("valid"), privateKey: Data(repeating: 5, count: 32)))
    }
    func testExpiredFutureForgedAndCancellationPayloadsCannotBecomeCallWakes() throws {
        for name in ["expired", "future", "forged", "cancel"] {
            XCTAssertThrowsError(try decode(payload(name)), name)
        }
    }
    func testAuthenticatedCiphertextAndEnvelopeLimitsAreRequired() throws {
        var value = try XCTUnwrap(JSONSerialization.jsonObject(with: payload("valid")) as? [String: Any])
        var sealed = try XCTUnwrap(value["next_call"] as? [String: Any])
        let original = sealed
        var bytes = try XCTUnwrap(Data(base64Encoded: try XCTUnwrap(sealed["cipher"] as? String)))
        bytes[0] ^= 1
        sealed["cipher"] = bytes.base64EncodedString(); value["next_call"] = sealed
        XCTAssertThrowsError(try decode(JSONSerialization.data(withJSONObject: value)))
        sealed = original; sealed["v"] = true; value["next_call"] = sealed
        XCTAssertThrowsError(try decode(JSONSerialization.data(withJSONObject: value)))
        sealed = original; sealed["extra"] = 1; value["next_call"] = sealed
        XCTAssertThrowsError(try decode(JSONSerialization.data(withJSONObject: value)))
        value["next_call"] = original; value["aps"] = ["alert": "not a call payload"]
        XCTAssertThrowsError(try decode(JSONSerialization.data(withJSONObject: value)))
        XCTAssertThrowsError(try decode(Data(repeating: 0, count: 5121)))
    }
}
