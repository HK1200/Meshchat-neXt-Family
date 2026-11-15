import XCTest

final class ProbeUITests: XCTestCase {
    func testEmbeddedRuntimeSendsAndReceivesInWebKit() {
        let app = XCUIApplication()
        app.launch()
        let web = app.webViews.firstMatch
        XCTAssertTrue(web.staticTexts["neXt runtime ready"].waitForExistence(timeout: 45), app.debugDescription)
        for module in ["aiohttp", "RNS", "LXMF"] {
            let label = web.staticTexts.containing(NSPredicate(format: "label BEGINSWITH %@", module)).firstMatch
            XCTAssertTrue(label.exists, "Missing runtime module: \(module)")
        }
        let send = app.buttons["Send Reticulum test message"]
        XCTAssertTrue(send.waitForExistence(timeout: 10), app.debugDescription)
        send.tap()
        XCTAssertTrue(web.staticTexts["Signed echo received"].waitForExistence(timeout: 105), app.debugDescription)
    }
}
