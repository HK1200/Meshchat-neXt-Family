import XCTest

final class FamilyAutomaticCallUITests: XCTestCase {
    func testAutomaticChooserForApprovedSIPContactDoesNotCallAnUnavailableService() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--isolated-family-test"]
        app.launchEnvironment["FAMILY_TEST_PROFILE"] = UUID().uuidString
        // Only the private loopback interface is configured. No public peer or SIP account.
        app.launchEnvironment["FAMILY_TEST_HOST"] = "127.0.0.1"
        app.launchEnvironment["FAMILY_TEST_PORT"] = "9"
        app.launch()
        defer { app.terminate() }
        let password = "private-call-ui-test"
        fill(app.secureTextFields["setup-password"], password)
        fill(app.secureTextFields["setup-confirmation"], password)
        app.buttons["Create guardian access"].tap()
        let guardian = app.buttons["guardian-settings"]
        XCTAssertTrue(guardian.waitForExistence(timeout: 20))
        guardian.tap()
        fill(app.secureTextFields["unlock-password"], password)
        app.buttons["Unlock"].tap()
        let add = app.buttons["Add approved contact"]
        XCTAssertTrue(add.waitForExistence(timeout: 15))
        for _ in 0..<4 where !add.isHittable { app.swipeDown() }
        add.tap()
        let name = "Private Call Routing Fixture"
        fill(app.textFields["contact-name"], name)
        let sip = app.textFields["SIP extension or address"]
        for _ in 0..<3 where !sip.isHittable { app.swipeUp() }
        fill(sip, "sip:test@example.invalid")
        let save = app.buttons["Save approved contact"]
        let form = app.descendants(matching: .any).matching(identifier: "contact-approval-form").firstMatch
        for _ in 0..<4 where !save.isHittable { form.swipeUp() }
        XCTAssertTrue(save.isHittable)
        save.tap()
        XCTAssertTrue(app.buttons["Contact saved"].waitForExistence(timeout: 15), app.debugDescription)
        app.buttons["Back to settings"].tap()
        app.buttons["Done"].tap()
        let contact = app.buttons[name]
        XCTAssertTrue(contact.waitForExistence(timeout: 15))
        contact.tap()
        let call = app.buttons["Call \(name)"]
        XCTAssertTrue(call.waitForExistence(timeout: 10))
        call.tap()
        let start = app.buttons["start-approved-call"]
        XCTAssertTrue(start.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["No automatic calling method is available. You can try another method or send a message."].waitForExistence(timeout: 15), app.debugDescription)
        let method = app.descendants(matching: .any).matching(identifier: "call-method").firstMatch
        XCTAssertTrue(method.exists)
        XCTAssertTrue(method.label.contains("Automatic") || (method.value as? String)?.contains("Automatic") == true,
                      method.debugDescription)
        XCTAssertFalse(start.isEnabled, "An unregistered SIP account must not place a call")
    }

    private func fill(_ field: XCUIElement, _ value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        field.typeText(value)
    }
}
