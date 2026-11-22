import XCTest
import CoreImage

final class ProbeUITests: XCTestCase {
    private struct EchoFixture: Decodable {
        let message: String
        let address: String
        let port: Int
        let deleteMessage: String?
        let freshMessage: String?
        let locationReceipt: String?
    }

    func testContactCodeImportReviewsExistingContactWithoutRequestingCamera() throws {
        executionTimeAllowance = 180
        continueAfterFailure = false
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "peer", withExtension: "json"))
        let fixture = try JSONDecoder().decode(EchoFixture.self, from: Data(contentsOf: file))
        let app = XCUIApplication()
        app.terminate(); app.launchArguments = []; app.launch()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 60), app.debugDescription)
        let own = app.staticTexts["my-lxmf-address"].label
        app.buttons["show-my-contact-qr"].tap()
        let importing = app.buttons["next-import-contact"]
        XCTAssertTrue(importing.waitForExistence(timeout: 15), app.debugDescription)
        importing.tap()
        XCTAssertTrue(app.collectionViews["next-contact-import-form"].waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertTrue(app.buttons["next-contact-import-photo"].exists)
        XCTAssertFalse(app.alerts.firstMatch.exists)
        let paste = app.buttons["next-contact-import-paste"]
        XCTAssertTrue(paste.waitForExistence(timeout: 15), app.debugDescription)
        paste.tap()
        let address = app.staticTexts["next-contact-import-address"]
        XCTAssertTrue(address.waitForExistence(timeout: 30), app.debugDescription)
        XCTAssertEqual(address.label, fixture.address)
        XCTAssertTrue(app.staticTexts["Already saved as Simulator Echo"].exists, app.debugDescription)
        XCTAssertFalse(app.buttons["next-contact-import-save"].exists)
        XCTAssertFalse(app.alerts.firstMatch.exists)
        app.navigationBars["Add Reticulum contact"].buttons["Cancel"].tap()
        app.navigationBars["My contact QR"].buttons["Done"].tap()
        XCTAssertEqual(app.staticTexts["my-lxmf-address"].label, own)
    }

    func testConversationSendsAndReceivesSignedLXMF() throws {
        // The iPad run reached its final profile/restart checks at 600s.
        // This full feature walk remains bounded by the harness maximum;
        // retain every actual message, persistence and permission assertion.
        executionTimeAllowance = 900
        continueAfterFailure = false
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "peer", withExtension: "json"))
        let fixture = try JSONDecoder().decode(EchoFixture.self, from: Data(contentsOf: url))
        let app = XCUIApplication()
        app.launch()
        let connections = app.buttons["tcp-connections"]
        XCTAssertTrue(connections.waitForExistence(timeout: 60), app.debugDescription)
        verifyMailboxSettings(app)
        verifyMessageAlertSettings(app)
        verifyRNodeEditor(app)
        verifyMeshCoreSettings(app)
        verifyReticulumCallingOff(app)
        connections.tap()
        let form = app.collectionViews["next-tcp-form"]
        XCTAssertTrue(form.waitForExistence(timeout: 10))
        XCTAssertTrue(app.webViews.textViews.firstMatch.waitForNonExistence(timeout: 10),
                      "The inactive page must not be accessible behind the native form")
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
        // Exercise a real background/foreground transition before sending.
        // The same saved conversation must remain usable after listener resume.
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertTrue(app.buttons["tcp-connections"].waitForExistence(timeout: 30), app.debugDescription)
        let web = app.webViews.firstMatch
        let composer = web.textViews.firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 60), app.debugDescription)
        composer.tap()
        if !app.keyboards.firstMatch.waitForExistence(timeout: 3) { composer.tap() }
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        // Keep typing attached to the keyboard focus already established.
        // Retargeting a WebKit field can move focus during viewport updates.
        app.typeText(fixture.message)
        let typed = web.textViews.matching(NSPredicate(format: "value == %@", fixture.message)).firstMatch
        XCTAssertTrue(typed.waitForExistence(timeout: 15), app.debugDescription)
        let send = web.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", "Send", "Send (")).firstMatch
        XCTAssertTrue(send.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(send.isEnabled, app.debugDescription)
        send.tap()
        XCTAssertTrue(web.staticTexts["Echo: " + fixture.message].waitForExistence(timeout: 105), app.debugDescription)
        verifyOwnContactQR(app)
        verifyAttachmentExport(app)
        verifyProfilePreferences(app, reply: "Echo: " + fixture.message)
    }

    func testLocationControlsRequireExplicitRecipientsAndDefaultToForeground() {
        executionTimeAllowance = 180
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate(); app.launchArguments = []; app.launch()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 60), app.debugDescription)
        let address = app.staticTexts["my-lxmf-address"].label
        let control = app.buttons["next-location-settings"]
        XCTAssertTrue(control.waitForExistence(timeout: 30) && control.isHittable, app.debugDescription)
        control.tap()
        XCTAssertTrue(app.navigationBars["Location sharing"].waitForExistence(timeout: 15), app.debugDescription)
        let background = app.switches["next-location-background"]
        XCTAssertTrue(background.waitForExistence(timeout: 20), app.debugDescription)
        XCTAssertEqual(background.value as? String, "0", app.debugDescription)
        let start = app.buttons["next-location-start"]
        XCTAssertTrue(start.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertFalse(start.isEnabled, "No recipient was selected; opening this screen must not start GPS or sending.")
        app.buttons["next-location-done"].tap()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertEqual(app.staticTexts["my-lxmf-address"].label, address)
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 20), app.debugDescription)
    }

    func testZNativeLocationUsesPrivateReticulumAndStops() throws {
        executionTimeAllowance = 240
        continueAfterFailure = false
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "peer", withExtension: "json"))
        let fixture = try JSONDecoder().decode(EchoFixture.self, from: Data(contentsOf: file))
        let receipt = try XCTUnwrap(fixture.locationReceipt)
        let app = XCUIApplication()
        app.terminate()
        app.resetAuthorizationStatus(for: .location)
        app.launchArguments = []
        app.launchEnvironment["NEXT_PROBE_LOCATION_FIXTURE"] = "1"
        app.launch()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 60), app.debugDescription)
        app.buttons["next-location-settings"].tap()
        let form = app.collectionViews["next-location-form"]
        let recipient = app.switches["next-location-recipient"].firstMatch
        XCTAssertTrue(recipient.waitForExistence(timeout: 20), app.debugDescription)
        reveal(recipient, in: form)
        XCTAssertEqual(recipient.value as? String, "0")
        // A custom SwiftUI Toggle exposes both the whole label row and its
        // UISwitch. The row's midpoint is whitespace, not the switch thumb.
        let selector = recipient.switches.firstMatch
        XCTAssertTrue(selector.waitForExistence(timeout: 10), app.debugDescription)
        selector.tap()
        let selected = app.switches.matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "next-location-recipient", "1")).firstMatch
        XCTAssertTrue(selected.waitForExistence(timeout: 15), app.debugDescription)
        let start = app.buttons["next-location-start"]
        reveal(start, in: form)
        XCTAssertTrue(start.isEnabled, app.debugDescription)
        start.tap()
        // Approve only the expected location request, after explicit Start.
        // Other permission explanations remain unapproved and fully tested.
        let system = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let allow = system.alerts.buttons["Allow While Using App"]
        XCTAssertTrue(allow.waitForExistence(timeout: 15), system.debugDescription)
        allow.tap()
        let current = app.buttons["Stop all sharing"]
        XCTAssertTrue(current.waitForExistence(timeout: 20), app.debugDescription)
        app.buttons["next-location-done"].tap()
        let web = app.webViews.firstMatch
        // Receipt is created only after the private peer verifies the real
        // LXMF signature and the exact fresh synthetic CoreLocation telemetry.
        XCTAssertTrue(web.staticTexts[receipt].waitForExistence(timeout: 105), app.debugDescription)
        let stop = web.buttons["Stop sharing"].firstMatch
        XCTAssertTrue(stop.waitForExistence(timeout: 20), app.debugDescription)
        stop.tap()
        XCTAssertTrue(stop.waitForNonExistence(timeout: 20), app.debugDescription)
        app.buttons["next-location-settings"].tap()
        XCTAssertTrue(app.navigationBars["Location sharing"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.switches["next-location-recipient"].firstMatch.waitForExistence(timeout: 20))
        XCTAssertFalse(app.buttons["Stop all sharing"].exists, app.debugDescription)
        app.buttons["next-location-done"].tap()
        app.terminate()
        app.resetAuthorizationStatus(for: .location)
    }

    func testConversationDeletionKeepsContactAndAllowsFreshSignedReply() throws {
        executionTimeAllowance = 600
        continueAfterFailure = false
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "peer", withExtension: "json"))
        let fixture = try JSONDecoder().decode(EchoFixture.self, from: Data(contentsOf: file))
        let app = XCUIApplication()
        app.terminate()
        app.launchArguments = []
        app.launch()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 60), app.debugDescription)
        let ownAddress = app.staticTexts["my-lxmf-address"].label
        let web = app.webViews.firstMatch
        func sendPrivateMessage(_ text: String) -> String {
            let composer = web.textViews.firstMatch
            XCTAssertTrue(composer.waitForExistence(timeout: 60), app.debugDescription)
            composer.tap()
            if !app.keyboards.firstMatch.waitForExistence(timeout: 3) { composer.tap() }
            XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
            app.typeText(text)
            let typed = web.textViews.matching(NSPredicate(format: "value == %@", text)).firstMatch
            XCTAssertTrue(typed.waitForExistence(timeout: 15), app.debugDescription)
            let send = web.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", "Send", "Send (")).firstMatch
            XCTAssertTrue(send.waitForExistence(timeout: 10) && send.isEnabled, app.debugDescription)
            send.tap()
            let reply = "Echo: " + text
            XCTAssertTrue(web.staticTexts[reply].waitForExistence(timeout: 105), app.debugDescription)
            return reply
        }
        let deletedReply = sendPrivateMessage(try XCTUnwrap(fixture.deleteMessage))
        // The chat back button is visible on both layouts; the sidebar
        // Messages item is a Link and may be collapsed on a phone.
        let back = web.buttons["arrow-left"].firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 15), app.debugDescription)
        back.tap()
        let contact = web.staticTexts["Simulator Echo"].firstMatch
        XCTAssertTrue(contact.waitForExistence(timeout: 15), app.debugDescription)
        // Use the real selection control on both layouts. A phone long press
        // selects a row; the same explicit control is available on iPad.
        let selection = web.buttons.matching(NSPredicate(format: "label == %@ OR label == %@",
            "Selection mode", "checkbox-multiple-marked-outline")).firstMatch
        XCTAssertTrue(selection.waitForExistence(timeout: 10), app.debugDescription)
        selection.tap()
        XCTAssertTrue(web.staticTexts["0 selected"].waitForExistence(timeout: 10), app.debugDescription)
        // This disposable fixture has exactly one conversation. Use its
        // visible selection-toolbar checkbox after the layout has settled;
        // tapping a cached text frame can hit the iPad's moved row boundary.
        let selectAll = web.switches.firstMatch
        XCTAssertTrue(selectAll.exists && selectAll.isHittable, app.debugDescription)
        selectAll.tap()
        XCTAssertTrue(web.staticTexts["1 selected"].waitForExistence(timeout: 10), app.debugDescription)
        let delete = web.buttons["Delete"].firstMatch
        XCTAssertTrue(delete.waitForExistence(timeout: 10), app.debugDescription)
        delete.tap()
        XCTAssertTrue(web.staticTexts["Delete these conversations? All messages will be lost."].waitForExistence(timeout: 10), app.debugDescription)
        web.buttons["Confirm"].firstMatch.tap()
        XCTAssertTrue(contact.waitForNonExistence(timeout: 15), app.debugDescription)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 60), app.debugDescription)
        XCTAssertEqual(app.staticTexts["my-lxmf-address"].label, ownAddress)
        XCTAssertTrue(web.textViews.firstMatch.waitForExistence(timeout: 60), app.debugDescription)
        XCTAssertTrue(web.staticTexts[deletedReply].waitForNonExistence(timeout: 15), app.debugDescription)
        // The actual send API requires the saved contact after history was
        // removed. A fresh signed reply proves the contact remains usable.
        let freshReply = sendPrivateMessage(try XCTUnwrap(fixture.freshMessage))
        XCTAssertTrue(web.staticTexts[deletedReply].waitForNonExistence(timeout: 15), app.debugDescription)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["my-lxmf-address"].waitForExistence(timeout: 60), app.debugDescription)
        XCTAssertEqual(app.staticTexts["my-lxmf-address"].label, ownAddress)
        XCTAssertTrue(web.staticTexts[freshReply].waitForExistence(timeout: 60), app.debugDescription)
        XCTAssertTrue(web.staticTexts[deletedReply].waitForNonExistence(timeout: 15), app.debugDescription)
    }

    private func verifyReticulumCallingOff(_ app: XCUIApplication) {
        app.buttons["next-calling-menu"].tap()
        XCTAssertTrue(app.buttons["next-sip-settings"].waitForExistence(timeout: 10))
        app.buttons["next-reticulum-calling"].tap()
        let form = app.collectionViews["next-voice-form"]
        XCTAssertTrue(form.waitForExistence(timeout: 15), app.debugDescription)
        let off = app.staticTexts.matching(NSPredicate(format: "identifier == %@ AND label == %@", "next-voice-status", "Reticulum calling off")).firstMatch
        XCTAssertTrue(off.waitForExistence(timeout: 15), app.debugDescription)
        let enabled = app.switches["next-voice-enabled"]
        XCTAssertEqual(enabled.value as? String, "0")
        let target = app.textFields["next-voice-target"]
        reveal(target, in: form)
        replace(target, with: String(repeating: "a", count: 32), in: app)
        XCTAssertFalse(app.buttons["next-voice-call"].isEnabled)
        app.navigationBars["Reticulum calling"].buttons["Done"].tap()
    }

    private func verifyMailboxSettings(_ app: XCUIApplication) {
        let mailbox = app.buttons["next-mailbox-settings"]
        XCTAssertTrue(mailbox.waitForExistence(timeout: 15), app.debugDescription)
        // XCTest can subtract fractional screen coordinates as
        // 43.99999999999997 for an exact 44-point frame.
        let minimumTouch = 44.0 - 0.001
        XCTAssertGreaterThanOrEqual(mailbox.frame.width, minimumTouch)
        XCTAssertGreaterThanOrEqual(mailbox.frame.height, minimumTouch)
        let qr = app.buttons["show-my-contact-qr"]
        XCTAssertGreaterThanOrEqual(qr.frame.width, minimumTouch)
        XCTAssertGreaterThanOrEqual(qr.frame.height, minimumTouch)
        mailbox.tap()
        let form = app.collectionViews["next-mailbox-form"]
        XCTAssertTrue(form.waitForExistence(timeout: 15), app.debugDescription)
        let off = app.staticTexts.matching(NSPredicate(format: "identifier == %@ AND label == %@", "next-mailbox-status", "Off")).firstMatch
        XCTAssertTrue(off.waitForExistence(timeout: 15), app.debugDescription)
        let fallback = app.switches["next-mailbox-fallback"]
        XCTAssertEqual(fallback.value as? String, "0")
        XCTAssertTrue(fallback.isEnabled)
        XCTAssertTrue(fallback.isHittable)
        // XCTest chose the rounded corner (310,468) for a 309,467,61,28
        // switch frame. Target its center; retain the exact value assertion.
        fallback.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        let enabledFallback = app.switches.matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "next-mailbox-fallback", "1"
        )).firstMatch
        XCTAssertTrue(enabledFallback.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(fallback.value as? String, "1")
        let field = app.textFields["next-mailbox-address"]
        replace(field, with: "not-a-propagation-address", in: app)
        XCTAssertFalse(app.buttons["next-mailbox-save"].isEnabled)
        XCTAssertFalse(app.buttons["next-mailbox-sync"].isEnabled)
        // Dismiss the invalid unsaved draft. It must never select a relay.
        XCTAssertFalse(app.alerts.firstMatch.exists)
        let mailboxDone = app.navigationBars["Offline mailbox"].buttons["Done"]
        XCTAssertTrue(mailboxDone.isEnabled, "A background read must not disable Done")
        XCTAssertTrue(mailboxDone.isHittable)
        mailboxDone.tap()
        let mailboxDismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: form)
        XCTAssertEqual(XCTWaiter.wait(for: [mailboxDismissed], timeout: 10), .completed, app.debugDescription)
        XCTAssertTrue(app.buttons["tcp-connections"].isHittable)
        XCTAssertTrue(app.buttons["next-mailbox-settings"].isHittable)
        app.buttons["next-mailbox-settings"].tap()
        XCTAssertTrue(off.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertEqual(app.switches["next-mailbox-fallback"].value as? String, "0")
        XCTAssertFalse(app.buttons["next-mailbox-sync"].isEnabled)
        let receiving = app.buttons["next-push-settings"]
        reveal(receiving, in: form)
        receiving.tap()
        XCTAssertTrue(app.collectionViews["next-push-form"].waitForExistence(timeout: 15), app.debugDescription)
        let receivingOff = app.staticTexts.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "next-push-status", "Off"
        )).firstMatch
        XCTAssertTrue(receivingOff.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertTrue(app.staticTexts["next-push-unavailable"].exists)
        XCTAssertFalse(app.buttons["next-push-enable"].isEnabled)
        XCTAssertFalse(app.alerts.firstMatch.exists, "Opening optional settings must not request Apple permission")
        app.navigationBars["Mailbox push alerts"].buttons["Done"].tap()
        let recipients = app.buttons["next-recipient-alerts"]
        reveal(recipients, in: form)
        recipients.tap()
        let recipientForm = app.collectionViews["next-recipient-alert-form"]
        XCTAssertTrue(recipientForm.waitForExistence(timeout: 15), app.debugDescription)
        let routeOff = app.staticTexts.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "next-recipient-alert-status", "Off"
        )).firstMatch
        XCTAssertTrue(routeOff.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertFalse(app.buttons["next-recipient-alert-save"].isEnabled)
        for (identifier, value) in [
            ("next-recipient-alert-provider", "https://alerts.example.invalid"),
            ("next-recipient-alert-audience", "private simulator test"),
            ("next-recipient-alert-relay", String(repeating: "b", count: 32))
        ] {
            let field = app.textFields[identifier]
            reveal(field, in: recipientForm)
            replace(field, with: value, in: app)
        }
        let save = app.buttons["next-recipient-alert-save"]
        reveal(save, in: recipientForm)
        XCTAssertTrue(save.isEnabled, app.debugDescription)
        save.tap()
        let saved = app.staticTexts.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "next-recipient-alert-status", "Recipient alerts saved"
        )).firstMatch
        reveal(saved, in: recipientForm, up: false)
        XCTAssertTrue(saved.waitForExistence(timeout: 15), app.debugDescription)
        let remove = app.buttons["next-recipient-alert-remove"]
        reveal(remove, in: recipientForm)
        XCTAssertTrue(remove.isEnabled, app.debugDescription)
        remove.tap()
        reveal(routeOff, in: recipientForm, up: false)
        XCTAssertTrue(routeOff.waitForExistence(timeout: 15), app.debugDescription)
        app.navigationBars["Recipient alerts"].buttons["Done"].tap()
        app.navigationBars["Offline mailbox"].buttons["Done"].tap()
    }

    private func waitForNativeTheme(_ theme: String, in app: XCUIApplication) {
        // Evaluate identifier and value together in XCTest's remote query.
        // A KVC polling expectation can time out while taking a full WebKit
        // snapshot even when the native header already has the saved value.
        let header = app.staticTexts.matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "next-native-brand", theme
        )).firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 60), app.debugDescription)
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
        app.buttons["next-message-alerts"].tap()
        let checkup = app.buttons["next-open-permission-checkup"]
        reveal(checkup, in: app.collectionViews.firstMatch)
        checkup.tap()
        verifyPermissionSteps(app)
        XCTAssertTrue(app.buttons["tcp-connections"].exists)
    }

    func testSetupPermissionCheckupDoesNotRequestOptionalAccess() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        app.resetAuthorizationStatus(for: .location)
        app.launchArguments = ["--review-setup-permissions"]
        app.launch()
        let review = app.buttons["next-setup-permission-checkup"]
        XCTAssertTrue(review.waitForExistence(timeout: 30), app.debugDescription)
        review.tap()
        verifyPermissionSteps(app)
        XCTAssertTrue(review.exists, app.debugDescription)
        app.terminate()
    }

    private func verifyPermissionSteps(_ app: XCUIApplication) {
        let guide = app.navigationBars["Permission checkup"]
        XCTAssertTrue(guide.waitForExistence(timeout: 10), app.debugDescription)
        for index in 1...8 {
            XCTAssertEqual(app.staticTexts["next-permission-step"].label, "Step \(index) of 8")
            // Reviewing explanations must not request access, scan or connect.
            XCTAssertFalse(app.alerts.firstMatch.exists, app.debugDescription)
            if index < 8 { app.buttons["Next"].tap() }
        }
        app.buttons["Finish checkup"].tap()
        XCTAssertTrue(guide.waitForNonExistence(timeout: 10), app.debugDescription)
    }

    private func verifyAttachmentExport(_ app: XCUIApplication) {
        let web = app.webViews.firstMatch
        let files = web.buttons.matching(NSPredicate(format: "label CONTAINS %@", "next-test.txt"))
        let composer = web.textViews.firstMatch
        let sharing = web.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Share my location once")).firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 20) && sharing.exists, app.debugDescription)
        var visibleFile: XCUIElement?
        for _ in 0..<8 {
            // WebKit exposes overscanned rows as hittable even behind sticky
            // controls. Require a whole button inside the actual chat viewport.
            let top = sharing.frame.maxY + 12
            let bottom = composer.frame.minY - 12
            visibleFile = files.allElementsBoundByIndex.reversed().first { element in
                let frame = element.frame
                return element.isHittable && frame.height > 0 && frame.minY >= top && frame.maxY <= bottom
            }
            if visibleFile != nil { break }
            XCTAssertGreaterThan(bottom - top, 80, app.debugDescription)
            let origin = app.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            let start = origin.withOffset(CGVector(dx: composer.frame.midX, dy: bottom - 12))
            let end = origin.withOffset(CGVector(dx: composer.frame.midX, dy: max(top + 20, bottom - 180)))
            start.press(forDuration: 0.05, thenDragTo: end)
        }
        XCTAssertNotNil(visibleFile, app.debugDescription)
        visibleFile?.tap()
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
        name.tap()
        // The iPad recording shows hardware Command-A leaving the caret at
        // the start of a WebKit field. Use the visible iOS edit menu instead.
        name.press(forDuration: 1.2)
        let selectAll = app.descendants(matching: .any).matching(NSPredicate(
            format: "label == %@ AND (elementType == %d OR elementType == %d)",
            "Select All", Int(XCUIElement.ElementType.button.rawValue),
            Int(XCUIElement.ElementType.menuItem.rawValue)
        )).firstMatch
        XCTAssertTrue(selectAll.waitForExistence(timeout: 10), app.debugDescription)
        // The failure recording shows this menu remaining visible while
        // XCTest repeatedly stalls resolving MenuItem.tap(). Use the visible
        // element's current frame, without a second accessibility resolution.
        let menuFrame = selectAll.frame
        let appFrame = app.frame
        XCTAssertGreaterThan(menuFrame.width, 0)
        XCTAssertGreaterThan(menuFrame.height, 0)
        XCTAssertTrue(appFrame.contains(menuFrame), app.debugDescription)
        app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(
            dx: menuFrame.midX - appFrame.minX,
            dy: menuFrame.midY - appFrame.minY
        )).tap()
        // Type into the current keyboard focus, without retargeting the field
        // after the menu has selected its contents.
        app.typeText(XCUIKeyboardKey.delete.rawValue)
        let cleared = name.value as? String ?? ""
        XCTAssertTrue(cleared.isEmpty || cleared == "Display Name", app.debugDescription)
        // The field is now empty, so retargeting it cannot disturb a
        // selection. Keep the keyboard event attached to the intended input
        // and wait for WebKit's settled accessibility value before comparing.
        name.typeText("Simulator profile")
        let completeName = web.textFields.matching(NSPredicate(
            format: "placeholderValue == %@ AND value == %@", "Display Name", "Simulator profile"
        )).firstMatch
        XCTAssertTrue(completeName.waitForExistence(timeout: 30), app.debugDescription)
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
        waitForNativeTheme("dark", in: app)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["tcp-connections"].waitForExistence(timeout: 60), app.debugDescription)
        XCTAssertEqual(app.staticTexts["my-lxmf-address"].label, ownAddress)
        XCTAssertTrue(web.staticTexts[reply].waitForExistence(timeout: 60), app.debugDescription)
        waitForNativeTheme("dark", in: app)
        settings.tap()
        XCTAssertTrue(name.waitForExistence(timeout: 15))
        let restoredName = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "Simulator profile"), object: name)
        XCTAssertEqual(XCTWaiter.wait(for: [restoredName], timeout: 15), .completed, app.debugDescription)
        let light = web.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "weather-sunny Light Theme")).firstMatch
        revealWebButton(light, in: web)
        light.tap()
        waitForNativeTheme("light", in: app)
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
        app.buttons["Family contact"].tap()
        let familyImage = app.images["my-family-qr-image"]
        XCTAssertTrue(familyImage.waitForExistence(timeout: 20), app.debugDescription)
        guard let familyScreenshot = CIImage(data: familyImage.screenshot().pngRepresentation) else {
            XCTFail("Could not read the displayed Family contact QR"); return
        }
        let familyPayloads = detector.features(in: familyScreenshot).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        XCTAssertEqual(familyPayloads.count, 1)
        if let text = familyPayloads.first, let data = text.data(using: .utf8),
           let card = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            XCTAssertEqual(card["format"] as? String, "next-family-contact")
            XCTAssertEqual((card["addresses"] as? [String: String])?["lxmf"], address.label.lowercased())
            XCTAssertEqual((card["identityPublicKey"] as? String)?.count, 128)
            XCTAssertNil(card["identityPrivateKey"])
            XCTAssertNil(card["password"])
        } else { XCTFail("The displayed Family QR must decode to a contact card") }
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
        let bounds = form.frame
        let top = bounds.minY + 12
        let bottom = min(bounds.maxY - 16, XCUIApplication().frame.maxY - 52)
        func fullyVisible() -> Bool {
            guard element.exists, element.isHittable else { return false }
            let frame = element.frame
            return frame.height > 0 && frame.minY >= top && frame.maxY <= bottom
        }
        for _ in 0..<12 {
            if fullyVisible() { break }
            // AX can report a cell below the form's visible bottom as hittable.
            // Require the whole control above the home indicator before tapping.
            // Keep gestures short and inside the form so they cannot pull the
            // sheet itself closed.
            let start = form.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.7 : 0.4))
            let end = form.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.4 : 0.7))
            start.press(forDuration: 0.05, thenDragTo: end)
        }
        XCTAssertTrue(element.waitForExistence(timeout: 10) && element.isHittable && fullyVisible(), XCUIApplication().debugDescription)
    }

    private func replace(_ field: XCUIElement, with value: String, in app: XCUIApplication) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        let placeholder = field.placeholderValue ?? ""
        let reported = field.value as? String ?? ""
        let previous = reported == placeholder ? "" : reported
        XCTAssertTrue(field.isEnabled, app.debugDescription)
        field.tap()
        // The first touch after scrolling may stop deceleration rather than
        // focus the field. Require the real keyboard before sending any text.
        if !app.keyboards.firstMatch.waitForExistence(timeout: 3) { field.tap() }
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        if !previous.isEmpty {
            app.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count))
            let cleared = app.textFields.matching(NSPredicate(
                format: "identifier == %@ AND (value == nil OR value == '' OR value == %@)",
                field.identifier, placeholder
            )).firstMatch
            XCTAssertTrue(cleared.waitForExistence(timeout: 20), app.debugDescription)
        }
        // A new blank row has nothing to delete. Do not poll its placeholder
        // through a block predicate that repeatedly requests full AX snapshots.
        // The exact replacement and saved values below remain mandatory.
        app.typeText(value)
        // The video shows the complete hostname before accessibility finishes
        // publishing it. Wait for the exact value, never accept a prefix.
        // Match on the remote accessibility server rather than polling a
        // KVC property that repeatedly snapshots the entire embedded page.
        let updated = app.textFields.matching(NSPredicate(
            format: "identifier == %@ AND value == %@", field.identifier, value
        )).firstMatch
        XCTAssertTrue(updated.waitForExistence(timeout: 30), app.debugDescription)
        XCTAssertEqual(field.value as? String, value, app.debugDescription)
        // The recipient editor keeps its dismissal control in the native
        // navigation bar, independent of the OS keyboard accessory's lifetime.
        let routeDone = app.buttons["next-recipient-alert-done-typing"]
        let done = routeDone.exists ? routeDone : app.buttons["Done typing"]
        XCTAssertTrue(done.waitForExistence(timeout: 5), app.debugDescription)
        done.tap()
        dismissSimulatorSystemNotice()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5), app.debugDescription)
    }

    private func dismissSimulatorSystemNotice() {
        // The failure recording shows the keyboard already closed while this
        // simulator-only system banner remains over the app. Dismiss only the
        // positively identified notice; retain the actual keyboard assertion.
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let notice = springboard.staticTexts["Ready for Apple Intelligence"].firstMatch
        if notice.waitForExistence(timeout: 1) { notice.swipeUp() }
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
