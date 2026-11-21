import XCTest

final class SIPAccountDraftTests: XCTestCase {
    func testDefaultsRequireAnAccountAndPasswordWithoutConnectingAnything() {
        var value = NextSIPAccountDraft()
        XCTAssertNil(value.payload)
        XCTAssertEqual(value.host, "premium.hamsoverip.com")
        XCTAssertEqual(value.port, "5160")
        XCTAssertEqual(value.allowedNetworks, ["wifi", "mobile", "ethernet"])
        value.user = "9001"
        XCTAssertNil(value.payload)
        value.password = "synthetic fixture"
        XCTAssertEqual(value.payload?["op"] as? String, "save")
        let account = value.payload?["account"] as? [String: Any]
        XCTAssertEqual(account?["extension"] as? String, "9001")
        XCTAssertEqual(account?["port"] as? Int, 5160)
        XCTAssertNil(account?["password"])
    }
    func testEditKeepsASavedPasswordOutOfTheRequestUnlessExplicitlyReplaced() {
        var value = NextSIPAccountDraft()
        value.id = UUID().uuidString; value.user = "9001"
        XCTAssertNotNil(value.payload)
        XCTAssertNil(value.payload?["password"])
        value.password = "replacement fixture"
        XCTAssertEqual(value.payload?["password"] as? String, "replacement fixture")
    }
    func testInvalidServerPortAccountAndEmptyNetworkPolicyCannotSave() {
        var good = NextSIPAccountDraft(); good.user = "9001"; good.password = "fixture"
        for host in ["https://example.invalid", "../other", "127.0.0.1:55162", "bad\nhost", ""] {
            var value = good; value.host = host; XCTAssertNil(value.payload)
        }
        for port in ["0", "65536", "-1", "1.5", ""] {
            var value = good; value.port = port; XCTAssertNil(value.payload)
        }
        for user in ["bad\nuser", "bad user", "", String(repeating: "x", count: 65)] {
            var value = good; value.user = user; XCTAssertNil(value.payload)
        }
        good.wifi = false; good.mobile = false; good.ethernet = false
        XCTAssertNil(good.payload)
    }
    func testPasswordByteAndControlLimitsMatchTheNativeVault() {
        var value = NextSIPAccountDraft(); value.user = "9001"
        value.password = String(repeating: "é", count: 128)
        XCTAssertNotNil(value.payload)
        value.password += "é"; XCTAssertNil(value.payload)
        value.password = "bad\0secret"; XCTAssertNil(value.payload)
        value.password = "fixture"; value.label = "bad\nlabel"; XCTAssertNil(value.payload)
    }
}
