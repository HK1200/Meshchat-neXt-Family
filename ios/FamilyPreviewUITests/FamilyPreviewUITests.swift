import XCTest

final class FamilyPreviewUITests: XCTestCase {
    func testBundledPreviewOpensConversation() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
        let webView = app.webViews.firstMatch
        XCTAssertTrue(webView.staticTexts["Mom"].waitForExistence(timeout: 15))

        let textButton = webView.buttons.matching(
            NSPredicate(format: "label CONTAINS[c] %@", "Text")
        ).firstMatch
        XCTAssertTrue(textButton.exists)
        textButton.tap()

        XCTAssertTrue(webView.staticTexts["Text Mom"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
    }
}
