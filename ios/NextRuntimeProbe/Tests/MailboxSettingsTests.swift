import XCTest

final class MailboxSettingsTests: XCTestCase {
    func testMailboxAddressAcceptsOnlyPropagationHashOrExplicitOff() {
        XCTAssertEqual(NextMailboxAddress.normalize("  " + String(repeating: "AB", count: 16) + "  "), String(repeating: "ab", count: 16))
        XCTAssertEqual(NextMailboxAddress.normalize("  "), "")
        XCTAssertNil(NextMailboxAddress.normalize("rmap.world:4343"))
        XCTAssertNil(NextMailboxAddress.normalize(String(repeating: "a", count: 31)))
        XCTAssertNil(NextMailboxAddress.normalize(String(repeating: "g", count: 32)))
    }
    func testMailboxFallbackRequiresExplicitSavedBooleanAndAcceptsOlderState() throws {
        let legacy = try JSONDecoder().decode(NextMailboxState.self,
            from: Data(#"{"address":"","status":"off"}"#.utf8))
        XCTAssertNil(legacy.send_fallback)
        let enabled = try JSONDecoder().decode(NextMailboxState.self,
            from: Data(#"{"address":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"waiting","send_fallback":true}"#.utf8))
        XCTAssertEqual(enabled.send_fallback, true)
        XCTAssertThrowsError(try JSONDecoder().decode(NextMailboxState.self,
            from: Data(#"{"address":"","status":"off","send_fallback":"yes"}"#.utf8)))
    }
}
