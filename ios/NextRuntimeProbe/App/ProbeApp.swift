import SwiftUI
import WebKit

@main
struct ProbeApp: App {
    var body: some Scene {
        WindowGroup { ProbeScreen() }
    }
}

private struct PeerSettings: Encodable {
    let host: String
    let port: Int
    let address: String
}

private struct ProbeScreen: View {
    @AppStorage("tcpHost") private var host = "rmap.world"
    @AppStorage("tcpPort") private var port = "4343"
    @AppStorage("testAddress") private var contact = ""
    @State private var url: URL?
    @State private var address: String?
    @State private var error: String?
    @State private var starting = false

    private var simulator: Bool {
        guard let file = Bundle.main.resourceURL?.appendingPathComponent("staged/peer.json") else { return false }
        return FileManager.default.fileExists(atPath: file.path)
    }

    private var settings: PeerSettings? {
        guard let number = Int(port), (1...65535).contains(number),
              host.range(of: "^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$", options: .regularExpression) != nil,
              contact.range(of: "^[0-9A-Fa-f]{32}$", options: .regularExpression) != nil else { return nil }
        return PeerSettings(host: host, port: number, address: contact.lowercased())
    }

    var body: some View {
        Group {
            if let url {
                VStack(spacing: 0) {
                    if let address {
                        HStack {
                            Text("My LXMF address")
                            Spacer()
                            ShareLink(item: address)
                        }
                        .padding(.horizontal)
                        Text(address).font(.caption.monospaced()).textSelection(.enabled)
                    }
                    ProbeWebView(url: url)
                }
            } else if let error {
                ContentUnavailableView("neXt couldn’t start", systemImage: "exclamationmark.triangle",
                                       description: Text(error))
            } else if simulator || starting {
                ProgressView("Starting neXt…")
            } else {
                Form {
                    Section("Reticulum TCP peer") {
                        TextField("Hostname or IPv4 address", text: $host)
                            .keyboardType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        TextField("Port", text: $port).keyboardType(.numberPad)
                    }
                    Section("Test contact") {
                        TextField("LXMF address (32 hex characters)", text: $contact)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    Button("Open Messages") {
                        guard let settings else { return }
                        starting = true
                        Task { await launch(settings) }
                    }
                    .disabled(settings == nil)
                }
            }
        }
        .task {
            guard simulator, url == nil, error == nil, !starting else { return }
            starting = true
            await launch(nil)
        }
    }

    private func launch(_ settings: PeerSettings?) async {
        do {
            let result = try await Self.start(settings)
            address = result.address
            url = result.url
        } catch {
            self.error = error.localizedDescription
        }
    }

    private static func start(_ settings: PeerSettings?) async throws -> (url: URL, address: String?) {
        guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        let modules = resources.appendingPathComponent("staged")
        let directory = try FileManager.default.url(
            for: settings == nil ? .cachesDirectory : .applicationSupportDirectory,
            in: .userDomainMask, appropriateFor: nil, create: true
        )
        let ready = directory.appendingPathComponent("next-\(UUID().uuidString).url")
        let config = ready.deletingPathExtension().appendingPathExtension("json")
        let address = ready.deletingPathExtension().appendingPathExtension("address")
        let error = ready.deletingPathExtension().appendingPathExtension("error")
        if let settings {
            try JSONEncoder().encode(settings).write(to: config, options: .atomic)
        }
        let home = resources.appendingPathComponent("python").path
        let modulePath = modules.path
        let readyPath = ready.path
        DispatchQueue.global(qos: .userInitiated).async {
            next_probe_run(home, modulePath, readyPath)
        }
        defer {
            for file in [ready, config, address, error] {
                try? FileManager.default.removeItem(at: file)
            }
        }
        for _ in 0..<600 {
            if let problem = try? String(contentsOf: error, encoding: .utf8) {
                throw NSError(domain: "neXt", code: 1, userInfo: [NSLocalizedDescriptionKey: problem])
            }
            if let value = try? String(contentsOf: ready, encoding: .utf8),
               let url = URL(string: value), url.scheme == "http", url.host == "127.0.0.1", url.port != nil {
                return (url, try? String(contentsOf: address, encoding: .utf8))
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw URLError(.timedOut)
    }
}

private struct ProbeWebView: UIViewRepresentable {
    let url: URL

    func makeCoordinator() -> NavigationGuard { NavigationGuard(url: url) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    final class NavigationGuard: NSObject, WKNavigationDelegate {
        let url: URL
        init(url: URL) { self.url = url }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            let target = action.request.url
            let isLocal = target?.scheme == url.scheme && target?.host == url.host && target?.port == url.port
            decisionHandler(action.targetFrame?.isMainFrame == true && isLocal ? .allow : .cancel)
        }
    }
}
