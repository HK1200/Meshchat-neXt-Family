import XCTest

final class RuntimeAccessTests: XCTestCase {
    private let capability = String(repeating: "a", count: 43)
    private func info(pid: Int32? = nil, origin: String = "http://127.0.0.1:12345") throws -> Data {
        try JSONSerialization.data(withJSONObject: ["version": 1,
            "pid": pid ?? ProcessInfo.processInfo.processIdentifier, "origin": origin,
            "instance": String(repeating: "b", count: 32), "capability": capability])
    }
    func testNativeRequestsKeepBodyAndCSRFButRefuseOtherOrigins() throws {
        let client = NextHTTP(), base = try XCTUnwrap(URL(string: "http://127.0.0.1:12345/#/messages"))
        try client.configure(info(), for: base)
        var request = URLRequest(url: try XCTUnwrap(URL(string: "http://127.0.0.1:12345/api/v1/config")))
        request.httpMethod = "PATCH"
        request.httpBody = Data("{}".utf8)
        request.setValue("private-csrf-fixture", forHTTPHeaderField: "X-CSRF-Token")
        let result = try client.authorized(request)
        XCTAssertEqual(result.value(forHTTPHeaderField: "X-neXt-Session"), capability)
        XCTAssertEqual(result.value(forHTTPHeaderField: "X-CSRF-Token"), "private-csrf-fixture")
        XCTAssertEqual(result.httpBody, request.httpBody)
        XCTAssertFalse(result.httpShouldHandleCookies)
        for value in ["http://127.0.0.1:12346/", "https://example.invalid/", "http://localhost:12345/", "http://user@127.0.0.1:12345/"] {
            XCTAssertThrowsError(try client.authorized(URLRequest(url: XCTUnwrap(URL(string: value)))))
        }
    }
    func testStaleOrForeignProcessMetadataCannotAuthorizeRequests() throws {
        let client = NextHTTP(), base = try XCTUnwrap(URL(string: "http://127.0.0.1:12345/"))
        XCTAssertThrowsError(try client.configure(info(pid: -1), for: base))
        XCTAssertThrowsError(try client.configure(info(origin: "http://127.0.0.1:54321"), for: base))
        XCTAssertThrowsError(try client.authorized(URLRequest(url: base)))
        try client.configure(info(), for: base)
        XCTAssertNoThrow(try client.authorized(URLRequest(url: base)))
        XCTAssertThrowsError(try client.configure(info(pid: -1), for: base))
        XCTAssertThrowsError(try client.authorized(URLRequest(url: base)))
    }
}
