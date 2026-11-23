import XCTest

final class PreviewChecks: XCTestCase {
    func testOnlyASeparateDevelopmentAppCanBeInspectedWithoutResettingIt() throws {
        continueAfterFailure = false
        executionTimeAllowance = 90
        // Never accept a regular Family bundle or an arbitrary app from input.
        let next = "org.meshchat.next.ios.runtimeprobe.9GUBNZGGM5"
        let mailboxTest = "org.meshchat.family.ios.mailbox-test.9GUBNZGGM5"
        let target = ProcessInfo.processInfo.environment["NEXT_PHYSICAL_TARGET"] ?? next
        guard [next, mailboxTest].contains(target) else {
            XCTFail("Only a separate development app may be tested"); return
        }
        let app = XCUIApplication(bundleIdentifier: target)
        // No launch arguments, profile reset, app removal or network edits.
        app.activate()
        XCTAssertEqual(app.state, .runningForeground, "The separate test app did not activate")
        if target == next {
            XCTAssertTrue(app.staticTexts["next-native-brand"].waitForExistence(timeout: 60),
                          "The separate preview has not opened its native header")
            XCTAssertTrue(app.buttons["tcp-connections"].waitForExistence(timeout: 15),
                          "The separate preview has no TCP settings control")
        } else {
            XCTAssertTrue(app.buttons.firstMatch.waitForExistence(timeout: 60),
                          "The separate test app has not rendered its controls")
        }
        XCTAssertGreaterThan(app.buttons.count, 0, "The test app's interface could not be inspected")
    }

    func testSeparateNextTCPMenuOpensAndClosesWithoutSaving() throws {
        continueAfterFailure = false
        executionTimeAllowance = 90
        let next = "org.meshchat.next.ios.runtimeprobe.9GUBNZGGM5"
        guard (ProcessInfo.processInfo.environment["NEXT_PHYSICAL_TARGET"] ?? next) == next else {
            XCTFail("The read-only TCP check targets only the separate neXt preview"); return
        }
        let app = XCUIApplication(bundleIdentifier: next)
        app.activate()
        XCTAssertTrue(app.staticTexts["next-native-brand"].waitForExistence(timeout: 60))
        let connections = app.buttons["tcp-connections"]
        XCTAssertTrue(connections.waitForExistence(timeout: 15))
        connections.tap()
        let navigation = app.navigationBars["TCP connections"]
        XCTAssertTrue(navigation.waitForExistence(timeout: 15))
        let done = navigation.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 15))
        // Never tap Save, edit a field, toggle a peer or add/remove a connection.
        done.tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: navigation)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 15), .completed)
        XCTAssertTrue(app.staticTexts["next-native-brand"].exists)
    }

}
