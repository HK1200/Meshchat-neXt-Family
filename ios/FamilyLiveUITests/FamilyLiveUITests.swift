import XCTest

final class FamilyLiveUITests: XCTestCase {
    private struct Peer: Decodable {
        let host: String
        let port: Int
        let address: String
        let message: String
        let reconnectMessage: String?
    }

    private enum Journey: Equatable { case messages, callRoute, voiceAndMaps }

    func testGuardianApprovedMessageRoundTrip() throws {
        try exerciseGuardianJourney(.messages)
    }

    #if !FAMILY_STORE_SCREENSHOTS
    func testGuardianVerifiedRecipientCallRoute() throws {
        try exerciseGuardianJourney(.callRoute)
    }

    func testGuardianVoiceAndOfflineMapControls() throws {
        try exerciseGuardianJourney(.voiceAndMaps)
    }
    #endif

    private func exerciseGuardianJourney(_ journey: Journey) throws {
        // Independent profiles keep every check without a ten-minute omnibus
        // case or relying on XCTest method order. Operation deadlines remain.
        executionTimeAllowance = 600
        continueAfterFailure = false
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "test-peer", withExtension: "json"))
        let peer = try JSONDecoder().decode(Peer.self, from: Data(contentsOf: file))
        let app = XCUIApplication()
        app.launchArguments = ["--isolated-family-test"]
        app.launchEnvironment["FAMILY_TEST_PROFILE"] = UUID().uuidString
        app.launchEnvironment["FAMILY_TEST_HOST"] = peer.host
        app.launchEnvironment["FAMILY_TEST_PORT"] = String(peer.port)
        let localTest = peer.host == "127.0.0.1"
        if localTest && journey == .messages {
            app.launchEnvironment["FAMILY_TEST_NOTIFICATIONS"] = "1"
            app.launchEnvironment["FAMILY_TEST_RECONNECT"] = "1"
        }
        app.launch()
        defer { app.terminate() }

        let appearance = app.buttons["appearance-toggle"]
        XCTAssertTrue(appearance.waitForExistence(timeout: 20))
        let previousAppearance = appearance.label
        appearance.tap()
        let changedAppearance = previousAppearance == "Day mode" ? "Night mode" : "Day mode"
        XCTAssertTrue(app.buttons[changedAppearance].waitForExistence(timeout: 5))

        let password = "simulator guardian test"
        fill(app.secureTextFields["setup-password"], password)
        fill(app.secureTextFields["setup-confirmation"], password)
        app.buttons["setup-password-visibility"].tap()
        XCTAssertEqual(app.textFields["setup-password"].value as? String, password)
        XCTAssertEqual(app.textFields["setup-confirmation"].value as? String, password)
        app.buttons["setup-password-visibility"].tap()
        XCTAssertTrue(app.secureTextFields["setup-password"].exists)
        XCTAssertTrue(app.secureTextFields["setup-confirmation"].exists)
        if localTest {
            let internet = app.switches["setup-internet-peers"]
            XCTAssertTrue(internet.waitForExistence(timeout: 10))
            for _ in 0..<3 where !internet.isHittable { app.swipeUp() }
            if internet.value as? String == "1" { internet.tap() }
            XCTAssertEqual(internet.value as? String, "0", "Local messaging tests must not enable public peers")
        }
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
        // SwiftUI forms on smaller screens may not expose off-screen rows.
        for _ in 0..<4 where !nameField.isHittable {
            peerForm.swipeDown()
        }
        XCTAssertTrue(nameField.isHittable, app.debugDescription)
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
        if localTest && journey == .messages {
            let discovery = app.buttons["Find messaging client"]
            XCTAssertTrue(discovery.waitForExistence(timeout: 10))
            if !discovery.isHittable { app.swipeUp() }
            discovery.tap()
            let query = app.textFields["Name or LXMF address"]
            fill(query, peer.address)
            XCTAssertEqual(query.value as? String, peer.address)
            // Do not search the lazy results while the keyboard hides them.
            // Use the actual keyboard's submit action, not a coordinate tap.
            if app.keyboards.firstMatch.exists {
                let done = app.buttons["finish-contact-entry"]
                if done.exists && done.isHittable { done.tap() }
                else { query.typeText("\n") }
                XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 10), app.debugDescription)
            }
            let result = app.buttons["discovered-client-\(peer.address)"]
            if !result.waitForExistence(timeout: 2) {
                let lookup = app.buttons["Look up address"]
                if lookup.exists && lookup.isEnabled { lookup.tap() }
            }
            XCTAssertTrue(result.waitForExistence(timeout: 35), app.debugDescription)
            reveal(result, in: app.collectionViews.firstMatch)
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
        if localTest && journey == .messages {
            let guardianForm = app.collectionViews["guardian-settings-form"]
            let edit = guardianForm.buttons[contactName]
            for _ in 0..<4 where !edit.isHittable { guardianForm.swipeDown() }
            XCTAssertTrue(edit.waitForExistence(timeout: 10))
            edit.tap()
            let editedName = app.textFields["edit-contact-name"]
            XCTAssertTrue(editedName.waitForExistence(timeout: 10))
            XCTAssertEqual(editedName.value as? String, contactName)
            let eraseName = String(repeating: XCUIKeyboardKey.delete.rawValue, count: contactName.count)
            fill(editedName, eraseName + "Unsaved guardian name")
            app.buttons["finish-contact-editor-entry"].tap()
            let meshDiscovery = app.buttons["Find MeshCore contact"]
            for _ in 0..<3 where !meshDiscovery.isHittable { app.swipeUp() }
            XCTAssertTrue(meshDiscovery.isHittable)
            meshDiscovery.tap()
            XCTAssertTrue(app.navigationBars["Find MeshCore contact"].waitForExistence(timeout: 10))
            app.navigationBars["Find MeshCore contact"].buttons.element(boundBy: 0).tap()
            for _ in 0..<3 where !editedName.isHittable { app.swipeDown() }
            XCTAssertEqual(editedName.value as? String, "Unsaved guardian name",
                           "Returning from discovery must not erase unsaved contact edits")
            app.navigationBars["Edit contact"].buttons.element(boundBy: 0).tap()
        }
        app.buttons["Done"].tap()

        XCTAssertTrue(app.staticTexts["Reticulum TCP connected"].waitForExistence(timeout: 25))
        #if FAMILY_STORE_SCREENSHOTS
        XCTAssertFalse(app.staticTexts["relay-chat-ready"].exists)
        #else
        XCTAssertTrue(app.staticTexts["relay-chat-ready"].waitForExistence(timeout: 15))
        #endif
        if localTest && journey == .messages {
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
        #if FAMILY_STORE_SCREENSHOTS
        captureListingScreen(app, named: "01-approved-contacts")
        #endif
        if journey != .voiceAndMaps {
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
            if localTest && journey == .messages {
                XCTAssertTrue(app.staticTexts["Message notification delivered"].waitForExistence(timeout: 15))
                XCTAssertTrue(app.staticTexts["Native inbox signal received"].waitForExistence(timeout: 15))
                XCTAssertTrue(app.staticTexts["Reticulum TCP reconnected"].waitForExistence(timeout: 30))
                let reconnectMessage = try XCTUnwrap(peer.reconnectMessage)
                fill(app.textFields["message-draft"], reconnectMessage)
                app.buttons["Send"].tap()
                // The newly inserted reply is above a focused composer in a lazy
                // Form. Dismiss editing and reveal it; require the exact signed
                // echo, rather than treating a hidden row as missing delivery.
                let finish = app.buttons["finish-message-entry"]
                if app.keyboards.firstMatch.exists {
                    XCTAssertTrue(finish.waitForExistence(timeout: 10))
                    finish.tap()
                }
                let echo = app.staticTexts["Echo: " + reconnectMessage]
                let conversation = app.collectionViews["private-conversation-form"]
                XCTAssertTrue(conversation.waitForExistence(timeout: 10))
                let deadline = Date().addingTimeInterval(90)
                var swipes = 0
                while !echo.exists && Date() < deadline {
                    if echo.waitForExistence(timeout: 1) { break }
                    if swipes % 12 < 6 { conversation.swipeDown() }
                    else { conversation.swipeUp() }
                    swipes += 1
                }
                XCTAssertTrue(echo.exists, app.debugDescription)
            }
        }
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons[contactName].waitForExistence(timeout: 30))
        XCTAssertTrue(app.navigationBars[deviceName].exists)
        XCTAssertTrue(app.buttons[changedAppearance].exists)
        #if FAMILY_STORE_SCREENSHOTS
        // Reopen the saved conversation after relaunch so the composer has no focus.
        app.buttons[contactName].tap()
        XCTAssertTrue(app.staticTexts["Echo: " + peer.message].waitForExistence(timeout: 15))
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        let banner = XCUIApplication(bundleIdentifier: "com.apple.springboard").staticTexts["New Family message"]
        let cleared = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: banner)
        XCTAssertEqual(XCTWaiter.wait(for: [cleared], timeout: 15), .completed)
        captureListingScreen(app, named: "02-approved-conversation")
        let back = app.navigationBars[contactName].buttons.firstMatch
        XCTAssertTrue(back.exists, app.debugDescription)
        back.tap()
        #endif
        XCTAssertTrue(guardian.waitForExistence(timeout: 10))
        if !guardian.isHittable { app.swipeUp() }
        guardian.tap()
        let locked = app.secureTextFields["unlock-password"]
        if !locked.waitForExistence(timeout: 5), guardian.isHittable { guardian.tap() }
        XCTAssertTrue(locked.waitForExistence(timeout: 10), app.debugDescription)
        if localTest && journey != .messages {
            fill(locked, password)
            app.buttons["Unlock"].tap()
            if journey == .callRoute {
                verifyRecipientCallRoute(app, contactName: contactName, address: peer.address)
            } else {
                let voice = app.buttons["Enable Reticulum calling"]
                for _ in 0..<4 where !voice.isHittable { app.swipeUp() }
                XCTAssertTrue(voice.waitForExistence(timeout: 10), app.debugDescription)
                voice.tap()
                let ready = app.staticTexts["reticulum-voice-ready"]
                let callingForm = app.collectionViews["guardian-settings-form"]
                // SwiftUI virtualizes off-screen rows. Search in both directions using
                // short drags; two full drags can scroll past the ready row on iPhone.
                for delta in Array(repeating: -0.12, count: 4) + Array(repeating: 0.12, count: 8) {
                    if ready.waitForExistence(timeout: 1) { break }
                    let start = callingForm.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.65))
                    let end = callingForm.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.65 + delta))
                    start.press(forDuration: 0.05, thenDragTo: end)
                }
                XCTAssertTrue(ready.waitForExistence(timeout: 35), app.debugDescription)
                let disableVoice = app.buttons["Disable Reticulum calling"]
                for _ in 0..<4 where !disableVoice.isHittable {
                    let start = callingForm.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.30))
                    let end = callingForm.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.70))
                    start.press(forDuration: 0.05, thenDragTo: end)
                }
                XCTAssertTrue(disableVoice.waitForExistence(timeout: 10) && disableVoice.isHittable, app.debugDescription)
                disableVoice.tap()
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
    }

    private func verifyRecipientCallRoute(_ app: XCUIApplication, contactName: String, address: String) {
        let guardian = app.collectionViews["guardian-settings-form"]
        let contact = guardian.buttons[contactName]
        reveal(contact, in: guardian, up: false)
        contact.tap()
        let editor = app.collectionViews["contact-editor-form"]
        let findVoice = app.buttons["Find voice address from approved messaging identity"]
        reveal(findVoice, in: editor)
        findVoice.tap()
        let voice = app.textFields["Reticulum voice address"]
        let resolved = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value MATCHES %@", "[a-f0-9]{32}"), object: voice)
        XCTAssertEqual(XCTWaiter.wait(for: [resolved], timeout: 15), .completed, app.debugDescription)
        let saveContact = app.buttons["Save contact"]
        reveal(saveContact, in: editor); saveContact.tap()
        XCTAssertTrue(app.navigationBars["Guardian settings"].waitForExistence(timeout: 15))
        XCTAssertTrue(guardian.waitForExistence(timeout: 15))
        reveal(contact, in: guardian, up: false); contact.tap()
        let open = app.buttons["contact-call-alert-route"]
        reveal(open, in: editor); open.tap()
        let form = app.collectionViews["contact-call-alert-route-form"]
        XCTAssertTrue(form.waitForExistence(timeout: 10))
        let provider = app.textFields["contact-call-alert-provider"]
        fill(provider, "https://example.invalid")
        fill(app.textFields["contact-call-alert-audience"], "private-calls")
        let done = app.buttons["Done typing"]
        XCTAssertTrue(done.waitForExistence(timeout: 10)); done.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 10))
        let save = app.buttons["Save call-alert route"]
        reveal(save, in: form); XCTAssertTrue(save.isEnabled); save.tap()
        XCTAssertTrue(app.navigationBars["Edit contact"].waitForExistence(timeout: 15))
        XCTAssertTrue(editor.waitForExistence(timeout: 15))
        reveal(open, in: editor); open.tap()
        XCTAssertTrue(form.waitForExistence(timeout: 10))
        XCTAssertEqual(provider.value as? String, "https://example.invalid")
        XCTAssertEqual(app.textFields["contact-call-alert-audience"].value as? String, "private-calls")
        let remove = app.buttons["Remove call-alert route"]
        reveal(remove, in: form); remove.tap()
        XCTAssertTrue(app.navigationBars["Edit contact"].waitForExistence(timeout: 15))
        XCTAssertTrue(editor.waitForExistence(timeout: 15))
        reveal(open, in: editor); open.tap()
        XCTAssertTrue(form.waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["Remove call-alert route"].exists)
        XCTAssertFalse(app.buttons["Save call-alert route"].isEnabled)
        app.navigationBars["Contact call alerts"].buttons.element(boundBy: 0).tap()
        reveal(app.textFields["LXMF address"], in: editor, up: false)
        XCTAssertEqual(app.textFields["LXMF address"].value as? String, address)
        XCTAssertEqual(app.textFields["edit-contact-name"].value as? String, contactName)
        app.navigationBars["Edit contact"].buttons.element(boundBy: 0).tap()
        XCTAssertTrue(guardian.waitForExistence(timeout: 10))
    }

    private func reveal(_ element: XCUIElement, in form: XCUIElement, up: Bool = true) {
        let app = XCUIApplication()
        XCTAssertTrue(form.waitForExistence(timeout: 10))
        for _ in 0..<10 {
            if element.exists && element.isHittable { break }
            let start = form.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.72 : 0.38))
            let end = form.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.40 : 0.70))
            start.press(forDuration: 0.05, thenDragTo: end)
        }
        XCTAssertTrue(element.exists && element.isHittable, app.debugDescription)
    }

    private func fill(_ field: XCUIElement, _ value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        if !field.isHittable { XCUIApplication().swipeUp() }
        field.tap()
        field.typeText(value)
    }
    #if FAMILY_STORE_SCREENSHOTS
    private func captureListingScreen(_ app: XCUIApplication, named name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "family-store-\(name)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    #endif

}
