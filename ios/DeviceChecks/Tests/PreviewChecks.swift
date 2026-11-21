import XCTest

final class PreviewChecks: XCTestCase {
    func testOnlyASeparateDevelopmentAppCanBeInspectedWithoutResettingIt() throws {
        continueAfterFailure = false
        executionTimeAllowance = 90
        // Never accept a regular Family bundle or an arbitrary app from input.
        let next = "org.meshchat.next.ios.runtimeprobe.9GUBNZGGM5"
        let mailboxTest = "org.meshchat.family.ios.mailbox-test.9GUBNZGGM5"
        let target = ProcessInfo.processInfo.environment["NEXT_PHYSICAL_TARGET"] ?? next
        guard [next, mailboxTest].contains(target) else {
            XCTFail("Only a separate development app may be tested"); return
        }
        let app = XCUIApplication(bundleIdentifier: target)
        // No launch arguments, profile reset, app removal or network edits.
        app.activate()
        XCTAssertEqual(app.state, .runningForeground, "The separate test app did not activate")
        XCTAssertGreaterThan(app.buttons.count, 0, "The test app's interface could not be inspected")
        if target == next {
            XCTAssertTrue(app.staticTexts["next-native-brand"].waitForExistence(timeout: 60),
                          "The separate preview has not opened its native header")
            XCTAssertTrue(app.buttons["tcp-connections"].exists,
                          "The separate preview has no TCP settings control")
        }
    }
}
