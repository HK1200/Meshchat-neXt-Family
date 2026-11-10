import XCTest

final class FamilyPreviewUITests: XCTestCase {
    func testBundledPreviewOpensConversation() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
        let webView = app.webViews.firstMatch
        let textButton = webView.buttons["Text Mom"]
        XCTAssertTrue(textButton.waitForExistence(timeout: 30))
        let night = webView.buttons["Switch to night mode"]
        let day = webView.buttons["Switch to day mode"]
        let wasNight = day.exists
        (wasNight ? day : night).tap()
        XCTAssertTrue((wasNight ? night : day).waitForExistence(timeout: 5))
        app.terminate()
        app.launch()
        XCTAssertTrue((wasNight ? night : day).waitForExistence(timeout: 30))
        textButton.tap()

        XCTAssertTrue(webView.textFields["Message"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
    }
}
