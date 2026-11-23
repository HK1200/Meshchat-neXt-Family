import XCTest

final class PreviewChecks: XCTestCase {
    private let family = "org.meshchat.family.ios.mailbox-test.9GUBNZGGM5"
    private func separateFamily() throws -> XCUIApplication {
        guard ProcessInfo.processInfo.environment["NEXT_PHYSICAL_TARGET"] == family else {
            XCTFail("Only the separate Family Mailbox Test app may be inspected")
            throw NSError(domain: "ReadOnlyDeviceChecks", code: 1)
        }
        let app = XCUIApplication(bundleIdentifier: family)
        // Activate normally: no resets, test profile, input data or permissions.
        app.activate()
        XCTAssertEqual(app.state, .runningForeground)
        XCTAssertTrue(app.buttons["guardian-settings"].waitForExistence(timeout: 60))
        return app
    }
    func testSeparateFamilyHomeIsInspectableWithoutResettingIt() throws {
        continueAfterFailure = false
        executionTimeAllowance = 90
        let app = try separateFamily()
        XCTAssertTrue(app.buttons["appearance-toggle"].exists)
        XCTAssertGreaterThan(app.buttons.count, 0)
    }
    func testSeparateFamilyGuardianGateOpensAndClosesWithoutUnlocking() throws {
        continueAfterFailure = false
        executionTimeAllowance = 90
        let app = try separateFamily()
        app.buttons["guardian-settings"].tap()
        let navigation = app.navigationBars["Guardian settings"]
        XCTAssertTrue(navigation.waitForExistence(timeout: 15))
        XCTAssertTrue(app.secureTextFields["unlock-password"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Unlock"].exists)
        // Never type a password, unlock settings, save or toggle anything.
        let done = navigation.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 15))
        done.tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: navigation)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 15), .completed)
        XCTAssertTrue(app.buttons["guardian-settings"].exists)
    }
}
