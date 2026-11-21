import XCTest

final class MeshCoreSecretTests: XCTestCase {
    private let owner = String(repeating: "a", count: 64)
    private let peer = String(repeating: "b", count: 64)

    private func call(_ store: NextMeshCoreSecrets, _ operation: String,
                      role: String = "member", owner: String? = nil, password: String? = nil) throws -> [String: Any] {
        var value: [String: Any] = ["operation": operation, "owner": owner ?? self.owner, "peer": peer, "role": role]
        if let password { value["password"] = password }
        let data = try JSONSerialization.data(withJSONObject: value)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(store.request(String(decoding: data, as: UTF8.self)).utf8)) as? [String: Any])
    }

    func testActualKeychainSaveUpdateReadAndForget() throws {
        let store = NextMeshCoreSecrets(service: "next.secret-test." + UUID().uuidString)
        defer { _ = try? call(store, "forget") }
        XCTAssertEqual(try call(store, "has")["value"] as? Bool, false)
        XCTAssertEqual(try call(store, "save", password: "private test one")["value"] as? Bool, true)
        XCTAssertEqual(try call(store, "has")["value"] as? Bool, true)
        XCTAssertEqual(try call(store, "load")["value"] as? String, "private test one")
        XCTAssertEqual(try call(store, "save", password: "private test two")["value"] as? Bool, true)
        XCTAssertEqual(try call(store, "load")["value"] as? String, "private test two")
        XCTAssertEqual(try call(store, "forget")["value"] as? Bool, true)
        XCTAssertEqual(try call(store, "has")["value"] as? Bool, false)
        XCTAssertNotNil(try call(store, "load")["error"])
    }

    func testRadioOwnerAndRoleDoNotSharePasswords() throws {
        let store = NextMeshCoreSecrets(service: "next.secret-test." + UUID().uuidString)
        defer { _ = try? call(store, "forget") }
        _ = try call(store, "save", password: "member test")
        XCTAssertEqual(try call(store, "has", role: "admin")["value"] as? Bool, false)
        XCTAssertEqual(try call(store, "has", owner: String(repeating: "c", count: 64))["value"] as? Bool, false)
    }

    func testInvalidSlotsAndOversizedPasswordsAreRejected() throws {
        let store = NextMeshCoreSecrets(service: "next.secret-test." + UUID().uuidString)
        for invalid in ["", "https://example.invalid", owner + "\n"] {
            XCTAssertNotNil(try call(store, "save", owner: invalid, password: "private")["error"])
        }
        XCTAssertNotNil(try call(store, "save", role: "anything", password: "private")["error"])
        XCTAssertNotNil(try call(store, "save", password: String(repeating: "é", count: 33))["error"])
        XCTAssertNotNil(try call(store, "save", password: "with\0nul")["error"])
        XCTAssertEqual(try call(store, "has")["value"] as? Bool, false)
    }
}
