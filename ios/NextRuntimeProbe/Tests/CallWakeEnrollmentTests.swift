// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

@MainActor final class CallWakeEnrollmentTests: XCTestCase {
    private let marker = Data(repeating: 7, count: 32)
    private func record() throws -> NextCallWakeEnrollment {
        let key = Curve25519.KeyAgreement.PrivateKey()
        let publicKey = key.publicKey.rawRepresentation + Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        let peer = Curve25519.KeyAgreement.PrivateKey().publicKey.rawRepresentation + Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        return NextCallWakeEnrollment(provider: URL(string: "https://example.invalid")!, audience: "private-calls",
            enrollmentCode: String(repeating: "a", count: 64), installation: marker, recipientPublicKey: publicKey,
            agreementPrivateKey: key.rawRepresentation,
            selectedCallers: [.init(publicKey: peer, voiceAddress: try FamilyCallWake.voiceAddress(publicKey: peer), name: "Test caller")],
            policyDigest: String(repeating: "b", count: 64))
    }
    func testNativeRoundTripRequiresTheSameInstallation() throws {
        let value = try record(), data = try value.encoded(installation: marker)
        XCTAssertNotNil(try NextCallWakeEnrollment.decode(data, installation: marker).context(installation: marker))
        XCTAssertThrowsError(try NextCallWakeEnrollment.decode(data, installation: Data(repeating: 8, count: 32)))
        XCTAssertNil(value.context(installation: Data()))
    }
    func testRevocationClearsAgreementMaterialBeforeRemoteRemoval() throws {
        var value = try record(); value.mayBeRegistered = true; value.beginRevocation()
        XCTAssertNil(value.agreementPrivateKey); XCTAssertNil(value.context(installation: marker))
        XCTAssertTrue(try NextCallWakeEnrollment.decode(value.encoded(installation: marker), installation: marker).revoking)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: value.subscription(token: Data(repeating: 2, count: 32))) as? [String: Any])
        XCTAssertTrue(body["token"] is NSNull); XCTAssertEqual(body["callers"] as? [String], [])
    }
    func testProviderDTOContainsOnlyPublicRoutingFields() throws {
        let value = try record(), body = try XCTUnwrap(JSONSerialization.jsonObject(with: value.subscription(token: Data(repeating: 2, count: 32))) as? [String: Any])
        XCTAssertEqual(Set(body.keys), ["recipient_key", "token", "callers"])
        XCTAssertEqual((body["recipient_key"] as? String)?.count, 128)
        XCTAssertEqual(body["callers"] as? [String], value.selectedCallers.map(\.voiceAddress))
        XCTAssertThrowsError(try value.subscription(token: Data(repeating: 0, count: 15)))
    }
    func testWrongAgreementKeyCannotCreateAColdWakeContext() throws {
        var value = try record(); value.agreementPrivateKey = Curve25519.KeyAgreement.PrivateKey().rawRepresentation
        XCTAssertNil(value.context(installation: marker)); XCTAssertThrowsError(try value.encoded(installation: marker))
    }
    func testVersionAndUnboundedDataFailClosed() throws {
        var value = try record(); value.version = 2
        XCTAssertThrowsError(try value.encoded(installation: marker))
        XCTAssertThrowsError(try NextCallWakeEnrollment.decode(Data(repeating: 0, count: NextCallWakeEnrollment.maximumBytes + 1), installation: marker))
    }
    func testUntrustedCallerBindingAndDuplicateVoiceAddressesFailClosed() throws {
        let value = try record(), peer = try XCTUnwrap(value.selectedCallers.first)
        func changed(_ callers: [NextCallWakeEnrollment.Caller]) -> NextCallWakeEnrollment {
            NextCallWakeEnrollment(provider: value.provider, audience: value.audience, enrollmentCode: value.enrollmentCode,
                installation: marker, recipientPublicKey: value.recipientPublicKey, agreementPrivateKey: value.agreementPrivateKey,
                selectedCallers: callers, policyDigest: value.policyDigest)
        }
        XCTAssertNil(changed([.init(publicKey: peer.publicKey, voiceAddress: String(repeating: "0", count: 32), name: "Wrong")]).context(installation: marker))
        XCTAssertNil(changed([peer, peer]).context(installation: marker))
    }
    func testProviderCredentialsPathsAndPlainHTTPAreRejected() throws {
        let original = try record().encoded(installation: marker)
        for provider in ["http://example.invalid", "https://user:pass@example.invalid", "https://example.invalid/path", "https://example.invalid?token=1", "https://example.invalid#secret"] {
            var json = try XCTUnwrap(JSONSerialization.jsonObject(with: original) as? [String: Any])
            json["provider"] = provider
            XCTAssertThrowsError(try NextCallWakeEnrollment.decode(JSONSerialization.data(withJSONObject: json), installation: marker), provider)
        }
    }
    func testAudienceUsesTheSameAlphabetAsTheSignedProtocol() throws {
        let original = try record().encoded(installation: marker)
        for audience in ["", "bad/audience", "private-calls\n", "emoji-🙂", "bad\nvalue", String(repeating: "a", count: 129)] {
            var json = try XCTUnwrap(JSONSerialization.jsonObject(with: original) as? [String: Any])
            json["audience"] = audience
            XCTAssertThrowsError(try NextCallWakeEnrollment.decode(JSONSerialization.data(withJSONObject: json), installation: marker))
        }
    }
    func testEnrollmentAndDigestMustMatchTheWholeString() throws {
        let original = try record().encoded(installation: marker)
        for key in ["enrollmentCode", "policyDigest"] {
            var json = try XCTUnwrap(JSONSerialization.jsonObject(with: original) as? [String: Any])
            json[key] = String(repeating: "a", count: 64) + "\n"
            XCTAssertThrowsError(try NextCallWakeEnrollment.decode(JSONSerialization.data(withJSONObject: json), installation: marker))
        }
    }
    func testRevokingRecordsCannotRetainPrivateAgreementMaterial() throws {
        var value = try record(); value.revoking = true
        XCTAssertNil(value.context(installation: marker))
        XCTAssertThrowsError(try value.encoded(installation: marker))
        value.beginRevocation()
        XCTAssertNoThrow(try value.encoded(installation: marker))
    }

    func testPausedConsentRetainsTheSelectionButCannotRingOrRegisterAToken() throws {
        var value = try record(); let selected = value.selectedCallers
        value.pausedForReview = true
        XCTAssertNil(value.context(installation: marker))
        let saved = try NextCallWakeEnrollment.decode(value.encoded(installation: marker), installation: marker)
        XCTAssertEqual(saved.selectedCallers, selected); XCTAssertNotNil(saved.agreementPrivateKey)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: value.subscription(token: Data(repeating: 1, count: 32))) as? [String: Any])
        XCTAssertTrue(body["token"] is NSNull); XCTAssertEqual(body["callers"] as? [String], [])
    }

}
