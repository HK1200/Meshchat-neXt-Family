import XCTest

final class FamilyLiveUITests: XCTestCase {
    private struct Peer: Decodable {
        let host: String
        let port: Int
        let address: String
        let message: String
        let reconnectMessage: String?
    }

    func testGuardianApprovedMessageRoundTrip() throws {
        continueAfterFailure = false
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "test-peer", withExtension: "json"))
        let peer = try JSONDecoder().decode(Peer.self, from: Data(contentsOf: file))
        let app = XCUIApplication()
        app.launchArguments = ["--isolated-family-test"]
        app.launchEnvironment["FAMILY_TEST_PROFILE"] = UUID().uuidString
        app.launchEnvironment["FAMILY_TEST_HOST"] = peer.host
        app.launchEnvironment["FAMILY_TEST_PORT"] = String(peer.port)
        let localTest = peer.host == "127.0.0.1"
        if localTest {
            app.launchEnvironment["FAMILY_TEST_NOTIFICATIONS"] = "1"
            app.launchEnvironment["FAMILY_TEST_RECONNECT"] = "1"
        }
        app.launch()

        let appearance = app.buttons["appearance-toggle"]
        XCTAssertTrue(appearance.waitForExistence(timeout: 20))
        let previousAppearance = appearance.label
        appearance.tap()
        let changedAppearance = previousAppearance == "Day mode" ? "Night mode" : "Day mode"
        XCTAssertTrue(app.buttons[changedAppearance].waitForExistence(timeout: 5))

        let password = "simulator guardian test"
        fill(app.secureTextFields["setup-password"], password)
        fill(app.secureTextFields["setup-confirmation"], password)
        app.buttons["Create guardian access"].tap()

        let guardian = app.buttons["guardian-settings"]
        XCTAssertTrue(guardian.waitForExistence(timeout: 20))
        guardian.tap()
        fill(app.secureTextFields["unlock-password"], password)
        app.buttons["Unlock"].tap()
        let savePeer = app.buttons["Save peer"]
        let enablePeer = app.buttons["peer-enabled"]
        let peerForm = app.collectionViews.firstMatch
        for _ in 0..<4 where !savePeer.isHittable {
            peerForm.swipeUp()
        }
        XCTAssertTrue(savePeer.waitForExistence(timeout: 10))
        XCTAssertTrue(enablePeer.exists)
        if enablePeer.label == "Enable Reticulum TCP peer" { enablePeer.tap() }
        XCTAssertEqual(enablePeer.label, "Disable Reticulum TCP peer")
        savePeer.tap()
        let connected = app.staticTexts["guardian-peer-connected"]
        for _ in 0..<3 where !connected.isHittable {
            peerForm.swipeDown()
        }
        XCTAssertTrue(connected.waitForExistence(timeout: 25), app.debugDescription)
        let deviceName = "Family simulator device"
        let nameField = app.textFields["device-name"]
        XCTAssertTrue(nameField.waitForExistence(timeout: 10))
        nameField.tap()
        // Clear the existing advertised name using the native text field's value.
        if let value = nameField.value as? String {
            nameField.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
        }
        nameField.typeText(deviceName)
        app.buttons["Save device name"].tap()
        XCTAssertTrue(app.staticTexts["Device name saved"].waitForExistence(timeout: 10))
        let addContact = app.buttons["Add approved contact"]
        if !addContact.isHittable { app.swipeDown() }
        XCTAssertTrue(addContact.waitForExistence(timeout: 10))
        addContact.tap()
        let contactName = localTest ? "Simulator echo peer" : "Echo peer"
        if localTest {
            let discovery = app.buttons["Find messaging client"]
            XCTAssertTrue(discovery.waitForExistence(timeout: 10))
            if !discovery.isHittable { app.swipeUp() }
            discovery.tap()
            fill(app.textFields["Name or LXMF address"], peer.address)
            let result = app.buttons["discovered-client-\(peer.address)"]
            if !result.exists {
                let lookup = app.buttons["Look up address"]
                if lookup.exists && lookup.isEnabled { lookup.tap() }
            }
            XCTAssertTrue(result.waitForExistence(timeout: 35))
            result.tap()
            XCTAssertEqual(app.textFields["contact-address"].value as? String, peer.address)
        } else {
            fill(app.textFields["contact-name"], contactName)
            fill(app.textFields["contact-address"], peer.address)
        }
        let saveContact = app.buttons["Save approved contact"]
        if !saveContact.isHittable { app.swipeUp() }
        saveContact.tap()
        XCTAssertTrue(app.buttons["Contact saved"].waitForExistence(timeout: 10))
        app.buttons["Back to settings"].tap()
        app.buttons["Done"].tap()

        XCTAssertTrue(app.staticTexts["Reticulum TCP connected"].waitForExistence(timeout: 25))
        XCTAssertTrue(app.staticTexts["relay-chat-ready"].waitForExistence(timeout: 15))
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
        let contact = app.buttons[contactName]
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
        XCTAssertTrue(
            app.staticTexts["Delivered"].waitForExistence(timeout: 90),
            "Delivery receipt missing. Conversation labels: \(app.staticTexts.allElementsBoundByIndex.map(\.label))"
        )
        XCTAssertTrue(app.staticTexts["Echo: " + peer.message].waitForExistence(timeout: 90))
        if localTest {
            XCTAssertTrue(app.staticTexts["Message notification delivered"].waitForExistence(timeout: 15))
            XCTAssertTrue(app.staticTexts["Reticulum TCP reconnected"].waitForExistence(timeout: 30))
            let reconnectMessage = try XCTUnwrap(peer.reconnectMessage)
            fill(app.textFields["message-draft"], reconnectMessage)
            app.buttons["Send"].tap()
            XCTAssertTrue(app.staticTexts["Echo: " + reconnectMessage].waitForExistence(timeout: 90))
        }
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons[contactName].waitForExistence(timeout: 30))
        XCTAssertTrue(app.navigationBars[deviceName].exists)
        XCTAssertTrue(app.buttons[changedAppearance].exists)
        XCTAssertTrue(guardian.waitForExistence(timeout: 10))
        if !guardian.isHittable { app.swipeUp() }
        guardian.tap()
        let locked = app.secureTextFields["unlock-password"]
        if !locked.waitForExistence(timeout: 5), guardian.isHittable { guardian.tap() }
        XCTAssertTrue(locked.waitForExistence(timeout: 10), app.debugDescription)
        if localTest {
            fill(locked, password)
            app.buttons["Unlock"].tap()
            let voice = app.buttons["Enable Reticulum calling"]
            for _ in 0..<4 where !voice.isHittable { app.swipeUp() }
            XCTAssertTrue(voice.waitForExistence(timeout: 10), app.debugDescription)
            voice.tap()
            XCTAssertTrue(app.staticTexts["reticulum-voice-ready"].waitForExistence(timeout: 35), app.debugDescription)
            app.buttons["Disable Reticulum calling"].tap()
            XCTAssertTrue(voice.waitForExistence(timeout: 10), app.debugDescription)
            let offlineMaps = app.buttons["Offline maps"]
            let guardianForm = app.collectionViews["guardian-settings-form"]
            XCTAssertTrue(guardianForm.waitForExistence(timeout: 10))
            let bottom = guardianForm.frame.maxY - 20
            for _ in 0..<6 {
                if offlineMaps.isHittable && offlineMaps.frame.midY < bottom { break }
                let start = guardianForm.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.85))
                let end = guardianForm.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.35))
                start.press(forDuration: 0.05, thenDragTo: end)
            }
            XCTAssertTrue(offlineMaps.isHittable && offlineMaps.frame.midY < bottom, app.debugDescription)
            offlineMaps.tap()
            let pnw = app.buttons["offline-map-layer-pnw"]
            XCTAssertTrue(pnw.waitForExistence(timeout: 10), app.debugDescription)
            pnw.tap()
            let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "Selected"), object: pnw)
            XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 10), .completed, app.debugDescription)
        }
    }

    private func fill(_ field: XCUIElement, _ value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        if !field.isHittable { XCUIApplication().swipeUp() }
        field.tap()
        field.typeText(value)
    }
}
