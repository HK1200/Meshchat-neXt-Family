import XCTest

final class ProbeUITests: XCTestCase {
    private struct EchoFixture: Decodable {
        let message: String
    }

    func testConversationSendsAndReceivesSignedLXMF() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "peer", withExtension: "json"))
        let fixture = try JSONDecoder().decode(EchoFixture.self, from: Data(contentsOf: url))
        let app = XCUIApplication()
        app.launch()
        let web = app.webViews.firstMatch
        let composer = web.textViews.firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 60), app.debugDescription)
        composer.tap()
        composer.typeText(fixture.message)
        let send = web.buttons.containing(NSPredicate(format: "label BEGINSWITH[c] %@", "Send")).firstMatch
        XCTAssertTrue(send.waitForExistence(timeout: 10), app.debugDescription)
        send.tap()
        XCTAssertTrue(web.staticTexts["Echo: " + fixture.message].waitForExistence(timeout: 105), app.debugDescription)
    }
}
