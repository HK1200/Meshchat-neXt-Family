import XCTest

final class ProbeUITests: XCTestCase {
    func testEmbeddedRuntimeRespondsInWebKit() {
        let app = XCUIApplication()
        app.launch()
        let web = app.webViews.firstMatch
        XCTAssertTrue(web.staticTexts["neXt runtime ready"].waitForExistence(timeout: 45), app.debugDescription)
        for module in ["aiohttp", "RNS", "LXMF"] {
            let label = web.staticTexts.containing(NSPredicate(format: "label BEGINSWITH %@", module)).firstMatch
            XCTAssertTrue(label.exists, "Missing runtime module: \(module)")
        }
    }
}
