import XCTest
import WebKit

@MainActor
final class ModalPageTests: XCTestCase {
    private final class Navigation: NSObject, WKNavigationDelegate {
        let ready: XCTestExpectation
        var error: Error?
        init(_ ready: XCTestExpectation) { self.ready = ready }
        func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) { ready.fulfill() }
        func webView(_ view: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            self.error = error; ready.fulfill()
        }
    }

    private func javascript(_ view: WKWebView, _ script: String,
                            arguments: [String: Any] = [:], isolated: Bool = false) async throws -> Any {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Any, Error>) in
            view.callAsyncJavaScript(script, arguments: arguments, in: nil,
                                     in: isolated ? .defaultClient : .page) { result in
                continuation.resume(with: result)
            }
        }
    }

    func testInterfaceReadinessRequiresTheRenderedAppNotAnEmptyDocument() async throws {
        let view = WKWebView(frame: CGRect(x: 0, y: 0, width: 480, height: 640))
        let ready = expectation(description: "Synthetic app document loaded")
        let navigation = Navigation(ready)
        view.navigationDelegate = navigation
        defer { view.stopLoading(); view.navigationDelegate = nil }
        view.loadHTMLString("<html><body><div id='app'></div></body></html>", baseURL: nil)
        await fulfillment(of: [ready], timeout: 30)
        XCTAssertNil(navigation.error)
        let empty = try await javascript(view, NextWebLoadState.pageReadyScript)
        XCTAssertEqual(empty as? Bool, false)
        _ = try await javascript(view, "document.getElementById('app').appendChild(document.createElement('main')); return true;")
        let rendered = try await javascript(view, NextWebLoadState.pageReadyScript)
        XCTAssertEqual(rendered as? Bool, true)
    }

    func testNativeModalHidesPageWithoutLosingDraftAndRestoresIt() async throws {
        try await verify(attributes: "", expectedAria: NSNull(), expectedInert: false)
    }

    func testNativeModalRestoresPreexistingAccessibilityAndInertState() async throws {
        try await verify(attributes: "aria-hidden='false' inert", expectedAria: "false", expectedInert: true)
    }

    private func verify(attributes: String, expectedAria: Any, expectedInert: Bool) async throws {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: CGRect(x: 0, y: 0, width: 480, height: 640), configuration: configuration)
        let ready = expectation(description: "Synthetic modal page loaded")
        let navigation = Navigation(ready)
        view.navigationDelegate = navigation
        defer { view.stopLoading(); view.navigationDelegate = nil }
        view.loadHTMLString("<html \(attributes)><body><textarea id='draft'>Unsent private draft</textarea></body></html>", baseURL: nil)
        await fulfillment(of: [ready], timeout: 30)
        XCTAssertNil(navigation.error)
        for _ in 0..<2 {
            let active = try await javascript(view, NextModalPage.script, arguments: ["active": true], isolated: true)
            XCTAssertEqual(active as? Bool, true)
        }
        let hiddenValue = try await javascript(view,
            "return {aria: document.documentElement.getAttribute('aria-hidden'), inert: document.documentElement.inert, draft: document.getElementById('draft').value};")
        let hidden = try XCTUnwrap(hiddenValue as? [String: Any])
        XCTAssertEqual(hidden["aria"] as? String, "true")
        XCTAssertEqual(hidden["inert"] as? Bool, true)
        XCTAssertEqual(hidden["draft"] as? String, "Unsent private draft")
        for _ in 0..<2 {
            _ = try await javascript(view, NextModalPage.script, arguments: ["active": false], isolated: true)
        }
        let restoredValue = try await javascript(view,
            "return {aria: document.documentElement.getAttribute('aria-hidden'), inert: document.documentElement.inert, draft: document.getElementById('draft').value};")
        let restored = try XCTUnwrap(restoredValue as? [String: Any])
        if expectedAria is NSNull { XCTAssertTrue(restored["aria"] is NSNull) }
        else { XCTAssertEqual(restored["aria"] as? String, expectedAria as? String) }
        XCTAssertEqual(restored["inert"] as? Bool, expectedInert)
        XCTAssertEqual(restored["draft"] as? String, "Unsent private draft")
    }
}
