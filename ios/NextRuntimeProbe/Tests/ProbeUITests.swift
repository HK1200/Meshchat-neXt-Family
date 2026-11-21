import XCTest
import CoreImage

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
        verifyMessageAlertSettings(app)
        verifyRNodeEditor(app)
        verifyMeshCoreSettings(app)
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
        verifySavedRNodeEditor(app)
        let web = app.webViews.firstMatch
        let composer = web.textViews.firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 60), app.debugDescription)
        composer.tap()
        composer.typeText(fixture.message)
        let send = web.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", "Send", "Send (")).firstMatch
        XCTAssertTrue(send.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(send.isEnabled, app.debugDescription)
        send.tap()
        XCTAssertTrue(web.staticTexts["Echo: " + fixture.message].waitForExistence(timeout: 105), app.debugDescription)
        verifyOwnContactQR(app)
        verifyAttachmentExport(app)
        verifyProfilePreferences(app, reply: "Echo: " + fixture.message)
    }

    private func verifyMeshCoreSettings(_ app: XCUIApplication) {
        let button = app.buttons["next-meshcore-settings"]
        XCTAssertTrue(button.exists)
        button.tap()
        let web = app.webViews.firstMatch
        XCTAssertTrue(web.staticTexts["MeshCore settings"].waitForExistence(timeout: 20), app.debugDescription)
        XCTAssertTrue(web.staticTexts["Disconnected"].waitForExistence(timeout: 10), app.debugDescription)
        // Viewing an unconfigured radio must not request Bluetooth or transmit.
        XCTAssertFalse(app.alerts.firstMatch.exists, app.debugDescription)
        button.tap()
        XCTAssertTrue(web.textViews.firstMatch.waitForExistence(timeout: 20), app.debugDescription)
    }

    private func verifyRNodeEditor(_ app: XCUIApplication) {
        app.buttons["next-rnode-settings"].tap()
        let form = app.collectionViews["next-rnode-form"]
        XCTAssertTrue(form.waitForExistence(timeout: 15), app.debugDescription)
        let status = app.staticTexts["next-rnode-status"]
        XCTAssertEqual(status.label, "Off")
        XCTAssertEqual(app.switches["next-rnode-enabled"].value as? String, "0")
        let transport = app.segmentedControls["next-rnode-transport"]
        transport.buttons["Wi-Fi"].tap()
        let endpoint = app.textFields["next-rnode-endpoint"]
        XCTAssertTrue(endpoint.waitForExistence(timeout: 10))
        endpoint.tap()
        endpoint.typeText("127.0.0.1")
        let typingDone = app.buttons["Done typing"]
        XCTAssertTrue(typingDone.waitForExistence(timeout: 10))
        typingDone.tap()
        let save = app.buttons["next-rnode-save"]
        reveal(save, in: form)
        XCTAssertTrue(save.isEnabled)
        save.tap()
        XCTAssertTrue(app.staticTexts["RNode settings saved"].waitForExistence(timeout: 10), app.debugDescription)
        // Saved disabled radio profiles must never trigger Bluetooth or RF.
        XCTAssertEqual(app.switches["next-rnode-enabled"].value as? String, "0")
        app.navigationBars["RNode"].buttons["Done"].tap()
        XCTAssertTrue(app.buttons["tcp-connections"].exists)
    }

    private func verifySavedRNodeEditor(_ app: XCUIApplication) {
        app.buttons["next-rnode-settings"].tap()
        let endpoint = app.textFields["next-rnode-endpoint"]
        XCTAssertTrue(endpoint.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertEqual(endpoint.value as? String, "127.0.0.1")
        XCTAssertEqual(app.switches["next-rnode-enabled"].value as? String, "0")
        app.navigationBars["RNode"].buttons["Done"].tap()
    }

    private func verifyMessageAlertSettings(_ app: XCUIApplication) {
        app.buttons["next-message-alerts"].tap()
        let navigation = app.navigationBars["Message alerts"]
        XCTAssertTrue(navigation.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.buttons["Allow message alerts"].exists || app.buttons["Open neXt settings"].exists)
        let limit = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "iOS may pause neXt")).firstMatch
        XCTAssertTrue(limit.exists, app.debugDescription)
        navigation.buttons["Done"].tap()
        XCTAssertTrue(navigation.waitForNonExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.buttons["tcp-connections"].exists)
    }

    private func verifyAttachmentExport(_ app: XCUIApplication) {
        let web = app.webViews.firstMatch
        let file = web.buttons.matching(NSPredicate(format: "label CONTAINS %@", "next-test.txt")).firstMatch
        for _ in 0..<6 where !file.isHittable { web.swipeUp() }
        XCTAssertTrue(file.waitForExistence(timeout: 20) && file.isHittable, app.debugDescription)
        file.tap()
        let name = app.staticTexts["export-attachment-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 30), app.debugDescription)
        XCTAssertEqual(name.label, "next-test.txt")
        XCTAssertTrue(app.buttons["share-attachment"].exists)
        app.navigationBars["Attachment"].buttons["Done"].tap()
        XCTAssertTrue(app.buttons["tcp-connections"].exists)
    }

    private func verifyProfilePreferences(_ app: XCUIApplication, reply: String) {
        let ownAddress = app.staticTexts["my-lxmf-address"].label
        let web = app.webViews.firstMatch
        let settings = web.buttons["Settings"].firstMatch
        XCTAssertTrue(settings.waitForExistence(timeout: 15), app.debugDescription)
        settings.tap()
        let name = web.textFields["Display Name"]
        XCTAssertTrue(name.waitForExistence(timeout: 15), app.debugDescription)
        let previous = name.value as? String ?? ""
        name.tap()
        // WebKit can place the insertion point at the beginning on tap.
        // The fixture name fits the field; tapping its trailing edge moves
        // the caret to the end before deleting the old text.
        name.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        name.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count))
        let cleared = name.value as? String ?? ""
        XCTAssertTrue(cleared.isEmpty || cleared == "Display Name", app.debugDescription)
        name.typeText("Simulator profile")
        XCTAssertEqual(name.value as? String, "Simulator profile", app.debugDescription)
        settings.tap()
        // Allow the released UI's 600 ms debounce to finish. The saved name
        // is asserted after terminating and reopening the app below, rather
        // than depending on a short-lived toast being exposed to XCTest.
        Thread.sleep(forTimeInterval: 1)
        let dark = web.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "weather-night Dark Theme")).firstMatch
        revealWebButton(dark, in: web)
        dark.tap()
        // Stop at the native header instead of asking WebKit to resolve every
        // Settings element for each polling sample. Large web accessibility
        // snapshots can exceed the wait even after the theme has applied.
        let brand = app.staticTexts.matching(identifier: "next-native-brand").firstMatch
        let darkApplied = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "dark"), object: brand)
        XCTAssertEqual(XCTWaiter.wait(for: [darkApplied], timeout: 15), .completed, app.debugDescription)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["tcp-connections"].waitForExistence(timeout: 60), app.debugDescription)
        XCTAssertEqual(app.staticTexts["my-lxmf-address"].label, ownAddress)
        XCTAssertTrue(web.staticTexts[reply].waitForExistence(timeout: 60), app.debugDescription)
        let restoredDark = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "dark"), object: brand)
        XCTAssertEqual(XCTWaiter.wait(for: [restoredDark], timeout: 15), .completed, app.debugDescription)
        settings.tap()
        XCTAssertTrue(name.waitForExistence(timeout: 15))
        let restoredName = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "Simulator profile"), object: name)
        XCTAssertEqual(XCTWaiter.wait(for: [restoredName], timeout: 15), .completed, app.debugDescription)
        let light = web.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "weather-sunny Light Theme")).firstMatch
        revealWebButton(light, in: web)
        light.tap()
        let lightApplied = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "light"), object: brand)
        XCTAssertEqual(XCTWaiter.wait(for: [lightApplied], timeout: 15), .completed, app.debugDescription)
    }

    private func revealWebButton(_ button: XCUIElement, in web: XCUIElement) {
        for _ in 0..<8 where !button.isHittable { web.swipeUp() }
        XCTAssertTrue(button.waitForExistence(timeout: 10) && button.isHittable, XCUIApplication().debugDescription)
    }

    private func verifyOwnContactQR(_ app: XCUIApplication) {
        let address = app.staticTexts["my-lxmf-address"]
        XCTAssertTrue(address.waitForExistence(timeout: 10))
        let expected = "lxmf://" + address.label.lowercased()
        let show = app.buttons["show-my-contact-qr"]
        XCTAssertTrue(show.waitForExistence(timeout: 10))
        show.tap()
        let image = app.images["my-lxmf-qr-image"]
        XCTAssertTrue(image.waitForExistence(timeout: 10), app.debugDescription)
        guard let captured = CIImage(data: image.screenshot().pngRepresentation),
              let detector = CIDetector(ofType: CIDetectorTypeQRCode, context: nil,
                                       options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]) else {
            XCTFail("Could not decode the displayed contact QR")
            return
        }
        let payloads = detector.features(in: captured).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        XCTAssertEqual(payloads, [expected], "The displayed QR must contain this device's actual messaging address")
        app.navigationBars["My contact QR"].buttons["Done"].tap()
        XCTAssertTrue(app.buttons["tcp-connections"].exists)
    }

    private func waitUntilLoaded(_ app: XCUIApplication) {
        let save = app.buttons["save-tcp-peers"]
        XCTAssertTrue(save.waitForExistence(timeout: 10))
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: save)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 15), .completed, app.debugDescription)
    }

    private func reveal(_ element: XCUIElement, in form: XCUIElement, up: Bool = true) {
        XCTAssertTrue(form.waitForExistence(timeout: 10), XCUIApplication().debugDescription)
        for _ in 0..<12 where !element.isHittable {
            // A full-height downward swipe can pull the sheet itself closed.
            // Keep the gesture short and inside the form's content area.
            let start = form.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.7 : 0.4))
            let end = form.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.4 : 0.7))
            start.press(forDuration: 0.05, thenDragTo: end)
        }
        XCTAssertTrue(element.waitForExistence(timeout: 10) && element.isHittable, XCUIApplication().debugDescription)
    }

    private func replace(_ field: XCUIElement, with value: String, in app: XCUIApplication) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        let previous = field.value as? String ?? ""
        XCTAssertTrue(field.isEnabled, app.debugDescription)
        field.tap()
        // The first touch after scrolling may stop deceleration rather than
        // focus the field. Require the real keyboard before sending any text.
        if !app.keyboards.firstMatch.waitForExistence(timeout: 3) { field.tap() }
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count) + value)
        XCTAssertEqual(field.value as? String, value, app.debugDescription)
        let done = app.buttons["Done typing"]
        XCTAssertTrue(done.waitForExistence(timeout: 5), app.debugDescription)
        done.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5), app.debugDescription)
    }

    private func saveConnections(_ app: XCUIApplication, form: XCUIElement) {
        let save = app.buttons["save-tcp-peers"]
        XCTAssertTrue(save.isEnabled)
        save.tap()
        let saved = app.staticTexts["tcp-peers-saved"]
        reveal(saved, in: form)
        waitUntilLoaded(app)
    }

}
