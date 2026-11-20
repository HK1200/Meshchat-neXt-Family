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
    let peers: [NextTCPPeer]
}

private struct ProbeScreen: View {
    @AppStorage("tcpHost") private var host = "rmap.world"
    @AppStorage("tcpPort") private var port = "4343"
    @AppStorage("testAddress") private var contact = ""
    @AppStorage("tcpPeers") private var savedPeers = ""
    @State private var showConnections = false
    @State private var showMyContactQR = false
    @State private var url: URL?
    @State private var address: String?
    @State private var error: String?
    @State private var starting = false
    @State private var theme = "system"
    @State private var tcpConnected: Bool?
    @State private var tcpEnabledCount: Int?

    private var simulator: Bool {
        guard let file = Bundle.main.resourceURL?.appendingPathComponent("staged/peer.json") else { return false }
        return FileManager.default.fileExists(atPath: file.path)
    }

    private var configuredPeers: [NextTCPPeer] {
        if let data = savedPeers.data(using: .utf8), let peers = try? JSONDecoder().decode([NextTCPPeer].self, from: data) {
            return peers
        }
        return NextTCPPeer.initial(host: host, port: Int(port) ?? 4343)
    }

    private var settings: PeerSettings? {
        guard contact.isEmpty || contact.range(of: "^[0-9A-Fa-f]{32}$", options: .regularExpression) != nil else { return nil }
        return PeerSettings(host: host, port: Int(port) ?? 4343, address: contact.lowercased(), peers: configuredPeers)
    }

    var body: some View {
        Group {
            if let url {
                VStack(spacing: 0) {
                    HStack {
                        Text("neXt").font(.headline)
                            .accessibilityIdentifier("next-native-brand")
                            .accessibilityValue(theme)
                        Spacer()
                        Button("TCP connections") { showConnections = true }
                            .accessibilityIdentifier("tcp-connections")
                    }.padding(.horizontal)
                    if let address {
                        HStack {
                            Text("My LXMF address")
                            Spacer()
                            Button { showMyContactQR = true } label: {
                                Label("Show my contact QR code", systemImage: "qrcode").labelStyle(.iconOnly)
                            }
                            .accessibilityIdentifier("show-my-contact-qr")
                            ShareLink(item: address)
                        }
                        .padding(.horizontal)
                        Text(address).font(.caption.monospaced()).textSelection(.enabled)
                            .accessibilityIdentifier("my-lxmf-address")
                        Label(tcpConnected == true ? "Reticulum TCP connected" : tcpEnabledCount == 0 ? "Reticulum TCP off" : "No TCP peer connected",
                              systemImage: tcpConnected == true ? "link" : "link.badge.plus")
                            .font(.caption)
                            .padding(.vertical, 4)
                            .task(id: url) { await watchConnection(at: url) }
                    }
                    ProbeWebView(url: url)
                }
            } else if let error {
                VStack {
                    ContentUnavailableView("neXt couldn’t start", systemImage: "exclamationmark.triangle",
                                           description: Text(error))
                    Button("Review connection settings") { self.error = nil; starting = false }
                }
            } else if simulator || starting {
                ProgressView("Starting neXt…")
            } else {
                Form {
                    Section("Reticulum TCP connections") {
                        Text("\(configuredPeers.filter(\.enabled).count) enabled peers")
                        Button("Edit TCP connections") { showConnections = true }
                            .accessibilityIdentifier("tcp-connections")
                    }
                    Section("First contact (optional)") {
                        TextField("LXMF address (32 hex characters)", text: $contact)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    Button("Open Messages") {
                        guard let settings else { return }
                        starting = true
                        savedPeers = (try? NextTCPPeer.encodeSettings(configuredPeers)) ?? savedPeers
                        Task { await launch(settings) }
                    }
                    .disabled(settings == nil)
                }
            }
        }
        .preferredColorScheme(theme == "dark" ? .dark : theme == "light" ? .light : nil)
        .sheet(isPresented: $showConnections) {
            NextTCPConnections(base: url, initial: configuredPeers) { peers in
                savedPeers = (try? NextTCPPeer.encodeSettings(peers)) ?? savedPeers
            }
        }
        .sheet(isPresented: $showMyContactQR) {
            NextMyContactQR(address: address ?? "")
        }
        .task {
            guard url == nil, error == nil, !starting else { return }
            if simulator {
                starting = true
                await launch(savedPeers.isEmpty ? nil : settings)
            } else if (!savedPeers.isEmpty || ProcessInfo.processInfo.arguments.contains("--open-saved-conversation")),
                      let settings {
                // The USB regression test can reopen the saved conversation without
                // entering an address or interacting with the setup screen.
                starting = true
                await launch(settings)
            }
        }
    }

    private func watchConnection(at url: URL) async {
        guard let endpoint = URL(string: "/api/v1/preview/reticulum-connection", relativeTo: url) else { return }
        struct ConnectionStatus: Decodable {
            let connected: Bool
            let enabledCount: Int?
            let theme: String?
        }
        while !Task.isCancelled {
            do {
                var request = URLRequest(url: endpoint)
                request.timeoutInterval = 2
                let (data, _) = try await URLSession.shared.data(for: request)
                let status = try JSONDecoder().decode(ConnectionStatus.self, from: data)
                tcpConnected = status.connected
                tcpEnabledCount = status.enabledCount
                theme = status.theme ?? "system"
            } catch {
                tcpConnected = nil
            }
            do {
                try await Task.sleep(for: .seconds(3))
            } catch {
                return
            }
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
        if UIDevice.current.userInterfaceIdiom == .pad {
            // Use neXt's built-in compact panes when the iPad viewport is narrow.
            let compactSidebarDefaults = """
                if (window.innerWidth < 1024) {
                    for (const feature of ["app", "messages"]) {
                        const key = "meshchatnext.sidebar." + feature;
                        if (localStorage.getItem(key) === null) localStorage.setItem(key, "true");
                    }
                }
                """
            configuration.userContentController.addUserScript(
                WKUserScript(source: compactSidebarDefaults, injectionTime: .atDocumentStart,
                             forMainFrameOnly: true)
            )
        }
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
