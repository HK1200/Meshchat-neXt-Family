import XCTest
import WebKit
import Network

/// A private loopback page exercises the actual WebKit/native bridge, rather
/// than treating the separately passing JavaScript and file tests as proof.
@MainActor
final class WebPreferencesBridgeTests: XCTestCase {
    private final class Navigation: NSObject, WKNavigationDelegate {
        let finished: XCTestExpectation
        var error: Error?
        init(_ finished: XCTestExpectation) { self.finished = finished }
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { finished.fulfill() }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            self.error = error; finished.fulfill()
        }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            self.error = error; finished.fulfill()
        }
    }
    private func loopbackPage() async throws -> (NWListener, URL) {
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let listener = try NWListener(using: parameters)
        let ready = expectation(description: "Private HTTP fixture listening")
        listener.stateUpdateHandler = { state in if case .ready = state { ready.fulfill() } }
        listener.newConnectionHandler = { connection in
            connection.start(queue: DispatchQueue(label: "next-preferences-private-http"))
            connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { _, _, _, _ in
                let body = "<!doctype html><html><body>Private preference bridge</body></html>"
                let response = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n" + body
                connection.send(content: Data(response.utf8), completion: .contentProcessed { _ in connection.cancel() })
            }
        }
        listener.start(queue: DispatchQueue(label: "next-preferences-private-listener"))
        await fulfillment(of: [ready], timeout: 10)
        let port = try XCTUnwrap(listener.port)
        return (listener, try XCTUnwrap(URL(string: "http://127.0.0.1:\(port.rawValue)/")))
    }
    private func page(_ url: URL, folder: URL) async throws -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let bridge = NextWebPreferencesBridge(base: url, folder: folder, onError: {})
        try bridge.install(in: configuration)
        let view = WKWebView(frame: CGRect(x: 0, y: 0, width: 480, height: 640), configuration: configuration)
        let loaded = expectation(description: "Private page loaded")
        let navigation = Navigation(loaded)
        view.navigationDelegate = navigation
        view.load(URLRequest(url: url))
        await fulfillment(of: [loaded], timeout: 15)
        if let error = navigation.error { throw error }
        return view
    }
    private func javascript(_ view: WKWebView, _ source: String, arguments: [String: Any] = [:]) async throws -> Any {
        // Force the completion-handler overload. With its default nil callback,
        // Swift can otherwise select the Void method even beside try/await.
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Any, Error>) in
            view.callAsyncJavaScript(source, arguments: arguments, in: nil, in: .page) { result in
                continuation.resume(with: result)
            }
        }
    }
    func testRealWebKitBridgePersistsRestoresAndRejectsChildFrames() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("next-webkit-preferences-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let (server, url) = try await loopbackPage()
        defer { server.cancel() }
        let view = try await page(url, folder: folder)
        let features = "{\"reticulum\":true,\"meshcore\":false,\"sip\":false}"
        _ = try await javascript(view, "localStorage.setItem(key, value); return true;", arguments: ["key": NextWebPreferences.featureKey, "value": features])
        var persisted = false
        for _ in 0..<200 {
            if (try? NextWebPreferences(folder: folder).values[NextWebPreferences.featureKey]) == features { persisted = true; break }
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertTrue(persisted, "The real WebKit write was not acknowledged into the private preference file")
        let (secondServer, secondURL) = try await loopbackPage()
        defer { secondServer.cancel() }
        XCTAssertNotEqual(url.port, secondURL.port)
        let restored = try await page(secondURL, folder: folder)
        let value = try await javascript(restored, "return localStorage.getItem(key);", arguments: ["key": NextWebPreferences.featureKey])
        XCTAssertEqual(value as? String, features)
        let child = try await javascript(restored, """
            return await new Promise((resolve, reject) => {
                const child = document.createElement('iframe');
                const deadline = setTimeout(() => reject(new Error('No child bridge reply')), 5000);
                window.addEventListener('message', event => {
                    if (event.source === child.contentWindow && ['accepted','rejected'].includes(event.data)) {
                        clearTimeout(deadline); child.remove(); resolve(event.data);
                    }
                });
                child.srcdoc = '<script>window.webkit.messageHandlers.nextPreferences.postMessage({op:"clear"}).then(()=>parent.postMessage("accepted","*"),()=>parent.postMessage("rejected","*"));<\\/script>';
                document.body.appendChild(child);
            });
            """)
        XCTAssertEqual(child as? String, "rejected", "A child frame must not change private native preferences")
        XCTAssertEqual(try NextWebPreferences(folder: folder).values[NextWebPreferences.featureKey], features)
        for web in [view, restored] {
            web.stopLoading()
            web.configuration.userContentController.removeScriptMessageHandler(forName: "nextPreferences", contentWorld: .page)
        }
    }
}
