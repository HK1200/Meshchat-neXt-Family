import XCTest

final class MailboxSettingsTests: XCTestCase {
    func testMailboxAddressAcceptsOnlyPropagationHashOrExplicitOff() {
        XCTAssertEqual(NextMailboxAddress.normalize("  " + String(repeating: "AB", count: 16) + "  "), String(repeating: "ab", count: 16))
        XCTAssertEqual(NextMailboxAddress.normalize("  "), "")
        XCTAssertNil(NextMailboxAddress.normalize("rmap.world:4343"))
        XCTAssertNil(NextMailboxAddress.normalize(String(repeating: "a", count: 31)))
        XCTAssertNil(NextMailboxAddress.normalize(String(repeating: "g", count: 32)))
    }
}
