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
        let reopenedView = app.webViews.firstMatch
        let reopenedTextButton = reopenedView.buttons["Text Mom"]
        let message = reopenedView.textFields["Message"]
        XCTAssertTrue(reopenedTextButton.waitForExistence(timeout: 15))
        reopenedTextButton.tap()
        if !message.waitForExistence(timeout: 5), reopenedTextButton.isHittable {
            reopenedTextButton.tap()
        }
        XCTAssertTrue(message.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.staticTexts["iOS preview · Sample data only"].exists)
    }
}
