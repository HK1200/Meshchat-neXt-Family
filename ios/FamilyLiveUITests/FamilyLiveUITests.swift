import XCTest

final class FamilyLiveUITests: XCTestCase {
    private struct Peer: Decodable {
        let host: String
        let port: Int
        let address: String
        let message: String
    }

    func testGuardianApprovedMessageRoundTrip() throws {
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "test-peer", withExtension: "json"))
        let peer = try JSONDecoder().decode(Peer.self, from: Data(contentsOf: file))
        let app = XCUIApplication()
        app.launchArguments = ["--isolated-family-test"]
        app.launchEnvironment["FAMILY_TEST_HOST"] = peer.host
        app.launchEnvironment["FAMILY_TEST_PORT"] = String(peer.port)
        let localTest = peer.host == "127.0.0.1"
        if localTest { app.launchEnvironment["FAMILY_TEST_NOTIFICATIONS"] = "1" }
        app.launch()

        let password = "simulator guardian test"
        fill(app.secureTextFields["setup-password"], password)
        fill(app.secureTextFields["setup-confirmation"], password)
        app.buttons["Create guardian access"].tap()

        let guardian = app.buttons["Guardian settings"]
        XCTAssertTrue(guardian.waitForExistence(timeout: 20))
        guardian.tap()
        fill(app.secureTextFields["unlock-password"], password)
        app.buttons["Unlock"].tap()
        let savePeer = app.buttons["Save peer"]
        XCTAssertTrue(savePeer.waitForExistence(timeout: 10))
        savePeer.tap()
        fill(app.textFields["contact-name"], "Echo peer")
        fill(app.textFields["contact-address"], peer.address)
        let saveContact = app.buttons["Save approved contact"]
        if !saveContact.isHittable { app.swipeUp() }
        saveContact.tap()
        XCTAssertTrue(app.staticTexts["Contact saved"].waitForExistence(timeout: 10))
        app.buttons["Done"].tap()

        XCTAssertTrue(app.staticTexts["Reticulum TCP connected"].waitForExistence(timeout: 25))
        if localTest {
            let enableNotifications = app.buttons["Enable message notifications"]
            if enableNotifications.exists {
                enableNotifications.tap()
                let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
                let allow = springboard.alerts.buttons["Allow"]
                if allow.waitForExistence(timeout: 10) { allow.tap() }
                let dismissed = XCTNSPredicateExpectation(
                    predicate: NSPredicate(format: "exists == false"), object: enableNotifications
                )
                XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 10), .completed)
            }
        }
        let contact = app.buttons["Echo peer"]
        XCTAssertTrue(contact.waitForExistence(timeout: 10))
        contact.tap()
        fill(app.textFields["message-draft"], peer.message)
        app.buttons["Send"].tap()
        if localTest {
            XCUIDevice.shared.press(.home)
            let backgrounded = XCTNSPredicateExpectation(
                predicate: NSPredicate { _, _ in
                    app.state == .runningBackground || app.state == .runningBackgroundSuspended
                },
                object: nil
            )
            XCTAssertEqual(XCTWaiter.wait(for: [backgrounded], timeout: 10), .completed)
            app.activate()
        }
        XCTAssertTrue(app.staticTexts["Delivered"].waitForExistence(timeout: 90))
        XCTAssertTrue(app.staticTexts["Echo: " + peer.message].waitForExistence(timeout: 90))
        if localTest {
            XCTAssertTrue(app.staticTexts["Message notification delivered"].waitForExistence(timeout: 15))
        }
    }

    private func fill(_ field: XCUIElement, _ value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        if !field.isHittable { XCUIApplication().swipeUp() }
        field.tap()
        field.typeText(value)
    }
}
