import XCTest

final class FamilyPreviewUITests: XCTestCase {
    func testBundledPreviewOpensConversation() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
        let webView = app.webViews.firstMatch
        XCTAssertTrue(webView.staticTexts["Mom"].waitForExistence(timeout: 15))

        let textButton = webView.buttons["Text Mom"]
        XCTAssertTrue(textButton.waitForExistence(timeout: 10))
        textButton.tap()

        XCTAssertTrue(webView.textFields["Message"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
    }
}
