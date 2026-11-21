import XCTest

final class WebPreferencesTests: XCTestCase {
    private func temporary() throws -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("next-private-preferences-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        return folder
    }
    func testFeatureChoicesAndContactNumbersSurviveReloadWithoutSavingCredentials() throws {
        let folder = try temporary(), store = try NextWebPreferences(folder: folder)
        let features = "{\"reticulum\":true,\"meshcore\":false,\"sip\":false}"
        let contacts = "[{\"id\":\"private-contact\",\"name\":\"Private Test\",\"address\":\"9001\",\"numbers\":[{\"label\":\"Home\",\"address\":\"sip:9001@127.0.0.1:55162\"}],\"linked_contact\":\"\"}]"
        try store.apply(["op": "set", "key": NextWebPreferences.featureKey, "value": features])
        try store.apply(["op": "set", "key": NextWebPreferences.contactsKey, "value": contacts])
        let reloaded = try NextWebPreferences(folder: folder)
        XCTAssertEqual(reloaded.values[NextWebPreferences.featureKey], features)
        XCTAssertEqual(reloaded.values[NextWebPreferences.contactsKey], contacts)
        let file = folder.appendingPathComponent("next-web-preferences.json")
        let permissions = try FileManager.default.attributesOfItem(atPath: file.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(permissions?.intValue, 0o600)
    }
    func testSeparateWindowsPreserveEachOthersChanges() throws {
        let folder = try temporary()
        let first = try NextWebPreferences(folder: folder), second = try NextWebPreferences(folder: folder)
        try first.apply(["op": "set", "key": "meshchatnext.sidebar.app", "value": "true"])
        try second.apply(["op": "set", "key": "meshchatnext.sidebar.messages", "value": "false"])
        let current = try NextWebPreferences(folder: folder)
        XCTAssertEqual(current.values["meshchatnext.sidebar.app"], "true")
        XCTAssertEqual(current.values["meshchatnext.sidebar.messages"], "false")
    }
    func testInvalidOrSecretKeysCannotChangeTheSavedFile() throws {
        let folder = try temporary(), store = try NextWebPreferences(folder: folder)
        try store.apply(["op": "set", "key": "meshchatnext.sidebar.app", "value": "true"])
        let file = folder.appendingPathComponent("next-web-preferences.json"), before = try Data(contentsOf: file)
        let invalid: [[String: Any]] = [
            ["op": "set", "key": "access_token", "value": "not stored"],
            ["op": "set", "key": NextWebPreferences.featureKey, "value": "{\"sip\":1}"],
            ["op": "set", "key": NextWebPreferences.featureKey, "value": "{\"password\":true}"],
            ["op": "set", "key": NextWebPreferences.contactsKey, "value": "[{\"id\":\"x\",\"name\":\"Test\",\"address\":\"9001\",\"password\":\"not stored\"}]"],
            ["op": "set", "key": NextWebPreferences.contactsKey, "value": String(repeating: "x", count: 131073)],
            ["op": "set", "key": "meshchatnext.sidebar.app", "value": "true", "extra": "not stored"]
        ]
        for request in invalid { XCTAssertThrowsError(try store.apply(request)); XCTAssertEqual(try Data(contentsOf: file), before) }
    }
    func testClearingWebPreferencesPreservesTheTransportIdentity() throws {
        let folder = try temporary(), store = try NextWebPreferences(folder: folder)
        let identity = folder.appendingPathComponent("identity"), original = Data(repeating: 42, count: 64)
        try original.write(to: identity)
        try store.apply(["op": "set", "key": "meshchatnext.sidebar.app", "value": "true"])
        try store.apply(["op": "remove", "key": "meshchatnext.sidebar.app"])
        XCTAssertTrue(store.values.isEmpty)
        try store.apply(["op": "clear"])
        XCTAssertEqual(try Data(contentsOf: identity), original)
    }
    func testCorruptOrUnknownBackingDataIsPreservedForRecovery() throws {
        let folder = try temporary(), file = folder.appendingPathComponent("next-web-preferences.json")
        for data in [Data("invalid private JSON".utf8), Data("{\"unknown\":\"not overwritten\"}".utf8)] {
            try data.write(to: file)
            XCTAssertThrowsError(try NextWebPreferences(folder: folder))
            XCTAssertEqual(try Data(contentsOf: file), data)
        }
    }
}
