import XCTest

final class FamilyLiveUITests: XCTestCase {
    private struct Peer: Decodable {
        let host: String
        let port: Int
        let address: String
    }

    func testGuardianApprovedMessageRoundTrip() throws {
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "test-peer", withExtension: "json"))
        let peer = try JSONDecoder().decode(Peer.self, from: Data(contentsOf: file))
        let app = XCUIApplication()
        app.launchArguments = ["--isolated-family-test"]
        app.launchEnvironment["FAMILY_TEST_HOST"] = peer.host
        app.launchEnvironment["FAMILY_TEST_PORT"] = String(peer.port)
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
        let contact = app.buttons["Echo peer"]
        XCTAssertTrue(contact.waitForExistence(timeout: 10))
        contact.tap()
        fill(app.textFields["message-draft"], "Hello from simulator")
        app.buttons["Send"].tap()
        XCTAssertTrue(app.staticTexts["Delivered"].waitForExistence(timeout: 75))
        XCTAssertTrue(app.staticTexts["Echo: Hello from simulator"].waitForExistence(timeout: 75))
    }

    private func fill(_ field: XCUIElement, _ value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        if !field.isHittable { XCUIApplication().swipeUp() }
        field.tap()
        field.typeText(value)
    }
}
