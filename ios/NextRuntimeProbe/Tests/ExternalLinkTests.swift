import XCTest

final class ExternalLinkTests: XCTestCase {
    func testOrdinaryWebLinksRequireAnExplicitUserActivation() {
        for value in ["https://example.invalid/help", "http://192.0.2.1:8080/help", "https://[2001:db8::1]/help"] {
            let url = URL(string: value)
            XCTAssertTrue(NextExternalLinks.allows(url, userActivated: true))
            XCTAssertFalse(NextExternalLinks.allows(url, userActivated: false))
        }
    }
    func testExecutableLocalAndCredentialBearingLinksCannotOpenExternally() {
        for value in ["javascript:alert(1)", "data:text/html,private", "file:///private/file", "sip:9001@example.invalid", "mailto:person@example.invalid", "https://user:password@example.invalid/", "https://user@example.invalid/", "/settings"] {
            XCTAssertFalse(NextExternalLinks.allows(URL(string: value), userActivated: true), value)
        }
        XCTAssertFalse(NextExternalLinks.allows(nil, userActivated: true))
    }
    func testOversizedLinksCannotCrossTheNativeBoundary() {
        let url = URL(string: "https://example.invalid/?value=" + String(repeating: "x", count: 8192))
        XCTAssertFalse(NextExternalLinks.allows(url, userActivated: true))
    }
}
