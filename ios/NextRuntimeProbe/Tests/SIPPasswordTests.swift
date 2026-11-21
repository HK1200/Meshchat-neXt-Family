import XCTest

final class SIPPasswordTests: XCTestCase {
    private func store() -> NextSIPPasswords { NextSIPPasswords(service: "next.sip-password-test." + UUID().uuidString) }

    func testBridgeDispatchIsBoundedAndKeepsNodePasswordsSeparate() throws {
        let bridge = NextCredentials(meshcore: NextMeshCoreSecrets(service: "next.sip-bridge-node." + UUID().uuidString), sip: store())
        let account = UUID().uuidString
        func request(_ value: [String: Any]) throws -> [String: Any] {
            let data = try JSONSerialization.data(withJSONObject: value)
            let response = bridge.request(String(decoding: data, as: UTF8.self))
            return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(response.utf8)) as? [String: Any])
        }
        defer { _ = try? request(["domain": "sip", "op": "password-remove", "account": account]) }
        XCTAssertEqual(try request(["domain": "sip", "op": "password-save", "account": account, "password": "private bridge test"])["ok"] as? Bool, true)
        XCTAssertEqual(try request(["domain": "sip", "op": "password-load", "account": account])["value"] as? String, "private bridge test")
        XCTAssertEqual(try request(["domain": "other", "op": "password-load", "account": account])["ok"] as? Bool, false)
        XCTAssertEqual(bridge.request(String(repeating: "x", count: 16 * 1024 + 1)), "{\"ok\":false}")
        XCTAssertEqual(bridge.request("not json"), "{\"ok\":false}")
        let owner = String(repeating: "a", count: 64), peer = String(repeating: "b", count: 64)
        XCTAssertEqual(try request(["owner": owner, "peer": peer, "role": "member", "operation": "has"])["value"] as? Bool, false)
    }

    func testActualSaveUpdateReadAndAccountIsolation() throws {
        let vault = store(), account = UUID().uuidString, other = UUID().uuidString
        defer { _ = try? vault.perform(["op": "password-remove", "account": account]) }
        _ = try vault.perform(["op": "password-save", "account": account, "password": "private test value"])
        XCTAssertEqual(try vault.perform(["op": "password-load", "account": account])["value"] as? String, "private test value")
        XCTAssertThrowsError(try vault.perform(["op": "password-load", "account": other]))
        _ = try vault.perform(["op": "password-save", "account": account.lowercased(), "password": "updated private test"])
        XCTAssertEqual(try vault.perform(["op": "password-load", "account": account])["value"] as? String, "updated private test")
        _ = try vault.perform(["op": "password-remove", "account": account])
        _ = try vault.perform(["op": "password-remove", "account": account])
        XCTAssertThrowsError(try vault.perform(["op": "password-load", "account": account]))
    }

    func testByteLimitAndMalformedSlotsDoNotCreatePasswords() throws {
        let vault = store(), account = UUID().uuidString
        defer { _ = try? vault.perform(["op": "password-remove", "account": account]) }
        for password in ["", "with\0nul", String(repeating: "é", count: 129)] {
            XCTAssertThrowsError(try vault.perform(["op": "password-save", "account": account, "password": password]))
        }
        for invalid in ["", "../other", account + "\n"] {
            XCTAssertThrowsError(try vault.perform(["op": "password-save", "account": invalid, "password": "private test"]))
        }
        XCTAssertThrowsError(try vault.perform(["op": "password-load", "account": account]))
        let boundary = String(repeating: "é", count: 128)
        _ = try vault.perform(["op": "password-save", "account": account, "password": boundary])
        XCTAssertEqual(try vault.perform(["op": "password-load", "account": account])["value"] as? String, boundary)
    }
}
