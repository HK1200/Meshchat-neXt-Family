import SwiftUI
import WebKit

@main
struct ProbeApp: App {
    var body: some Scene {
        WindowGroup { ProbeScreen() }
    }
}

private struct ProbeScreen: View {
    @State private var url: URL?
    @State private var error: String?
    @State private var sendRequested = false

    var body: some View {
        Group {
            if let url {
                VStack(spacing: 0) {
                    Button("Send Reticulum test message") { sendRequested = true }
                        .disabled(sendRequested)
                        .padding()
                    ProbeWebView(url: url, sendRequested: sendRequested)
                }
            } else if let error {
                Text(error)
            } else {
                ProgressView("Starting neXt runtime probe…")
            }
        }
        .task {
            guard url == nil, error == nil else { return }
            do {
                url = try await Self.start()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private static func start() async throws -> URL {
        guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        let modules = resources.appendingPathComponent("staged")
        let cache = try FileManager.default.url(
            for: .cachesDirectory, in: .userDomainMask, appropriateFor: nil, create: true
        )
        let ready = cache.appendingPathComponent("probe-\(UUID().uuidString).url")
        let home = resources.appendingPathComponent("python").path
        let modulePath = modules.path
        let readyPath = ready.path
        DispatchQueue.global(qos: .userInitiated).async {
            next_probe_run(home, modulePath, readyPath)
        }
        defer { try? FileManager.default.removeItem(at: ready) }
        for _ in 0..<300 {
            if let value = try? String(contentsOf: ready, encoding: .utf8),
               let url = URL(string: value), url.scheme == "http", url.host == "127.0.0.1", url.port != nil {
                return url
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw URLError(.timedOut)
    }
}

private struct ProbeWebView: UIViewRepresentable {
    let url: URL
    let sendRequested: Bool

    func makeCoordinator() -> NavigationGuard { NavigationGuard(url: url) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        guard sendRequested, !context.coordinator.sent else { return }
        context.coordinator.sent = true
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("text/html", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 100
        view.load(request)
    }

    final class NavigationGuard: NSObject, WKNavigationDelegate {
        let url: URL
        var sent = false
        init(url: URL) { self.url = url }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(action.targetFrame?.isMainFrame == true && action.request.url == url ? .allow : .cancel)
        }
    }
}
