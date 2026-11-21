import XCTest

final class PreviewChecks: XCTestCase {
    func testSeparateNeXtPreviewCanBeInspectedWithoutResettingIt() throws {
        continueAfterFailure = false
        executionTimeAllowance = 90
        // Never accept a regular Family bundle or an arbitrary app from input.
        let permitted = "org.meshchat.next.ios.runtimeprobe.9GUBNZGGM5"
        let target = ProcessInfo.processInfo.environment["NEXT_PHYSICAL_TARGET"] ?? permitted
        guard target == permitted else {
            XCTFail("Only the separate neXt preview may be tested"); return
        }
        let app = XCUIApplication(bundleIdentifier: target)
        // No launch arguments, profile reset, app removal or network edits.
        app.activate()
        XCTAssertTrue(app.staticTexts["next-native-brand"].waitForExistence(timeout: 60),
                      "The separate preview has not opened its native header")
        XCTAssertTrue(app.buttons["tcp-connections"].exists,
                      "The separate preview has no TCP settings control")
    }
}
