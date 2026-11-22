import XCTest

final class MyContactCardTests: XCTestCase {
    private let address = String(repeating: "a", count: 32)
    private func response(_ updates: [String: Any] = [:]) throws -> Data {
        var card: [String: Any] = ["format": "next-family-contact", "version": 1,
            "name": "Private Test", "addresses": ["lxmf": address],
            "identityPublicKey": String(repeating: "b", count: 128)]
        card.merge(updates) { _, new in new }
        let text = String(decoding: try JSONSerialization.data(withJSONObject: card), as: UTF8.self)
        return try JSONSerialization.data(withJSONObject: ["contact_card": text])
    }

    func testAcceptsOwnPublicMessagingAndEnabledVoiceCard() throws {
        let data = try response(["addresses": ["lxmf": address, "lxst": String(repeating: "c", count: 32)]])
        let text = try NextFamilyCard.payload(from: data, expectedAddress: address)
        let card = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        XCTAssertEqual(card["name"] as? String, "Private Test")
        XCTAssertEqual((card["addresses"] as? [String: String])?["lxst"], String(repeating: "c", count: 32))
    }

    func testRejectsChangedIdentitySecretsAndUnrequestedServices() throws {
        let changes: [[String: Any]] = [
            ["addresses": ["lxmf": String(repeating: "c", count: 32)]],
            ["password": "example"], ["identityPrivateKey": String(repeating: "d", count: 128)],
            ["addresses": ["lxmf": address, "sip": "sip:example@invalid"]],
            ["identityPublicKey": "invalid"], ["version": true], ["version": 2],
            ["format": "other"], ["name": ""],
        ]
        for change in changes {
            XCTAssertThrowsError(try NextFamilyCard.payload(from: response(change), expectedAddress: address))
        }
    }

    func testRejectsOversizedAndMalformedResponses() throws {
        for data in [Data(repeating: 1, count: 16385), Data("invalid".utf8), Data("{}".utf8)] {
            XCTAssertThrowsError(try NextFamilyCard.payload(from: data, expectedAddress: address))
        }
    }
}
