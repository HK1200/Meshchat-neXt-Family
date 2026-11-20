import XCTest

final class ProbeUITests: XCTestCase {
    private struct EchoFixture: Decodable {
        let message: String
        let port: Int
    }

    func testConversationSendsAndReceivesSignedLXMF() throws {
        continueAfterFailure = false
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "peer", withExtension: "json"))
        let fixture = try JSONDecoder().decode(EchoFixture.self, from: Data(contentsOf: url))
        let app = XCUIApplication()
        app.launch()
        let connections = app.buttons["tcp-connections"]
        XCTAssertTrue(connections.waitForExistence(timeout: 60), app.debugDescription)
        connections.tap()
        let form = app.collectionViews["next-tcp-form"]
        XCTAssertTrue(form.waitForExistence(timeout: 10))
        waitUntilLoaded(app)
        let primary = app.textFields["tcp-peer-port-peer-0"]
        reveal(primary, in: form, up: false)
        XCTAssertEqual(primary.value as? String, String(fixture.port))
        let add = app.buttons["add-tcp-peer"]
        reveal(add, in: form)
        add.tap()
        let customHost = app.textFields.matching(NSPredicate(
            format: "identifier BEGINSWITH %@ AND identifier != %@", "tcp-peer-host-", "tcp-peer-host-peer-0"
        )).firstMatch
        reveal(customHost, in: form)
        replace(customHost, with: "127.0.0.1", in: app)
        let identifier = String(customHost.identifier.dropFirst("tcp-peer-host-".count))
        let customPort = app.textFields["tcp-peer-port-" + identifier]
        reveal(customPort, in: form)
        replace(customPort, with: "45454", in: app)
        saveConnections(app, form: form)
        reveal(customPort, in: form, up: false)
        replace(customPort, with: "45455", in: app)
        let enabled = app.switches["tcp-peer-enabled-" + identifier]
        reveal(enabled, in: form)
        XCTAssertEqual(enabled.value as? String, "0")
        enabled.tap()
        saveConnections(app, form: form)
        reveal(enabled, in: form)
        enabled.tap()
        saveConnections(app, form: form)
        app.navigationBars["TCP connections"].buttons["Done"].tap()
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["tcp-connections"].waitForExistence(timeout: 60), app.debugDescription)
        app.buttons["tcp-connections"].tap()
        let restoredForm = app.collectionViews["next-tcp-form"]
        waitUntilLoaded(app)
        let restoredPort = app.textFields["tcp-peer-port-" + identifier]
        reveal(restoredPort, in: restoredForm)
        XCTAssertEqual(restoredPort.value as? String, "45455")
        let restoredEnabled = app.switches["tcp-peer-enabled-" + identifier]
        reveal(restoredEnabled, in: restoredForm, up: false)
        XCTAssertEqual(restoredEnabled.value as? String, "0")
        let restoredPrimary = app.textFields["tcp-peer-port-peer-0"]
        reveal(restoredPrimary, in: restoredForm, up: false)
        XCTAssertEqual(restoredPrimary.value as? String, String(fixture.port))
        app.navigationBars["TCP connections"].buttons["Done"].tap()
        let web = app.webViews.firstMatch
        let composer = web.textViews.firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 60), app.debugDescription)
        composer.tap()
        composer.typeText(fixture.message)
        let send = web.buttons.containing(NSPredicate(format: "label BEGINSWITH[c] %@", "Send")).firstMatch
        XCTAssertTrue(send.waitForExistence(timeout: 10), app.debugDescription)
        send.tap()
        XCTAssertTrue(web.staticTexts["Echo: " + fixture.message].waitForExistence(timeout: 105), app.debugDescription)
    }

    private func waitUntilLoaded(_ app: XCUIApplication) {
        let save = app.buttons["save-tcp-peers"]
        XCTAssertTrue(save.waitForExistence(timeout: 10))
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: save)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 15), .completed, app.debugDescription)
    }

    private func reveal(_ element: XCUIElement, in form: XCUIElement, up: Bool = true) {
        for _ in 0..<6 where !element.isHittable {
            if up { form.swipeUp() } else { form.swipeDown() }
        }
        XCTAssertTrue(element.waitForExistence(timeout: 10) && element.isHittable, XCUIApplication().debugDescription)
    }

    private func replace(_ field: XCUIElement, with value: String, in app: XCUIApplication) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        let previous = field.value as? String ?? ""
        field.tap()
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count) + value)
        let done = app.buttons["Done typing"]
        if done.exists { done.tap() }
    }

    private func saveConnections(_ app: XCUIApplication, form: XCUIElement) {
        let save = app.buttons["save-tcp-peers"]
        XCTAssertTrue(save.isEnabled)
        save.tap()
        let saved = app.staticTexts["tcp-peers-saved"]
        reveal(saved, in: form)
    }

}
