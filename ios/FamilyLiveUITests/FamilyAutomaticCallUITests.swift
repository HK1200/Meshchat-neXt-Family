import XCTest

final class FamilyAutomaticCallUITests: XCTestCase {
    func testAutomaticChooserForApprovedSIPContactDoesNotCallAnUnavailableService() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--isolated-family-test"]
        app.launchEnvironment["FAMILY_TEST_PROFILE"] = UUID().uuidString
        // Guardian fields are prefilled with loopback; all internet peers are disabled below.
        // No SIP account is configured, and this test never presses Call.
        app.launchEnvironment["FAMILY_TEST_HOST"] = "127.0.0.1"
        app.launchEnvironment["FAMILY_TEST_PORT"] = "9"
        app.launch()
        defer { app.terminate() }
        let password = "private-call-ui-test"
        // These are synthetic fixture credentials, not a user's password.
        // Verify the real text fields before hiding them and submitting setup.
        let visibility = app.buttons["setup-password-visibility"]
        XCTAssertTrue(visibility.waitForExistence(timeout: 20))
        visibility.tap()
        fill(app.textFields["setup-password"], password)
        fill(app.textFields["setup-confirmation"], password)
        visibility.tap()
        let internet = app.switches["setup-internet-peers"]
        XCTAssertTrue(internet.waitForExistence(timeout: 10))
        for _ in 0..<3 where !internet.isHittable { app.swipeUp() }
        if internet.value as? String == "1" { internet.tap() }
        XCTAssertEqual(internet.value as? String, "0", "The private UI test must disable all internet peers before setup")
        app.buttons["Create guardian access"].tap()
        let guardian = app.buttons["guardian-settings"]
        XCTAssertTrue(guardian.waitForExistence(timeout: 20), app.debugDescription)
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
        XCTAssertEqual(sip.value as? String, "sip:test@example.invalid")
        if app.keyboards.firstMatch.exists {
            let finish = app.buttons["finish-contact-entry"]
            XCTAssertTrue(finish.waitForExistence(timeout: 10))
            finish.tap()
            let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                                      object: app.keyboards.firstMatch)
            XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 10), .completed)
        }
        for _ in 0..<4 where !save.isHittable { form.swipeUp() }
        XCTAssertTrue(save.isHittable, app.debugDescription)
        save.tap()
        XCTAssertTrue(app.buttons["Contact saved"].waitForExistence(timeout: 15), app.debugDescription)
        app.buttons["Back to settings"].tap()
        app.buttons["Done"].tap()
        let contact = app.buttons[name]
        XCTAssertTrue(contact.waitForExistence(timeout: 15))
        contact.tap()
        let messageMethod = app.descendants(matching: .any).matching(identifier: "message-method").firstMatch
        XCTAssertTrue(messageMethod.waitForExistence(timeout: 10))
        XCTAssertTrue(messageMethod.label.contains("Automatic") || (messageMethod.value as? String)?.contains("Automatic") == true,
                      messageMethod.debugDescription)
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
        XCTAssertFalse(app.staticTexts["call-method-error"].exists, "An unavailable method must not hide a runtime/packaging failure")
        XCTAssertFalse(start.isEnabled, "An unregistered SIP account must not place a call")
    }

    private func fill(_ field: XCUIElement, _ value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        let app = XCUIApplication()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        app.typeText(value)
        if field.elementType != .secureTextField {
            let entered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: field)
            XCTAssertEqual(XCTWaiter.wait(for: [entered], timeout: 10), .completed, app.debugDescription)
        }
    }
}
