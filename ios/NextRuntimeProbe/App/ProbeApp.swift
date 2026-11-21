import SwiftUI
import WebKit

@main
struct ProbeApp: App {
    @UIApplicationDelegateAdaptor(NextMessageAlerts.self) private var alerts
    var body: some Scene {
        WindowGroup { ProbeScreen(alerts: alerts) }
    }
}

private struct PeerSettings: Encodable {
    let host: String
    let port: Int
    let address: String
    let peers: [NextTCPPeer]
}

private struct ProbeScreen: View {
    @ObservedObject var alerts: NextMessageAlerts
    @Environment(\.scenePhase) private var scenePhase
    @State private var appActive = true
    private enum Panel: String, Identifiable {
        case alerts, rnode, connections, myContact, permissions
        var id: String { rawValue }
    }
    @State private var panel: Panel?
    @State private var meshcoreReturnURL: URL?
    @State private var radioWake: FamilyRadioWake?
    @AppStorage("tcpHost") private var host = "rmap.world"
    @AppStorage("tcpPort") private var port = "4343"
    @AppStorage("testAddress") private var contact = ""
    @AppStorage("tcpPeers") private var savedPeers = ""
    @State private var exportItem: NextExportItem?
    @State private var exportFolder: URL?
    @State private var exportError = ""
    @State private var showExportError = false
    @State private var showPreferencesError = false
    @State private var preferencesError = ""
    @State private var routingMeshCoreAlert = false
    @State private var notificationRouteError: String?
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

    private var setupReviewFixture: Bool {
        // Only disposable simulator bundles contain peer.json. This displays
        // the real setup form without starting a transport for its UI test.
        simulator && ProcessInfo.processInfo.arguments.contains("--review-setup-permissions")
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
                        Button { panel = .alerts } label: {
                            Label("Message alerts", systemImage: "bell.badge").labelStyle(.iconOnly).frame(width: 44, height: 44)
                        }.accessibilityIdentifier("next-message-alerts")
                        Button { panel = .rnode } label: {
                            Label("RNode", systemImage: "antenna.radiowaves.left.and.right").labelStyle(.iconOnly).frame(width: 44, height: 44)
                        }.accessibilityIdentifier("next-rnode-settings")
                        Button {
                            if let previous = meshcoreReturnURL {
                                self.url = previous
                                meshcoreReturnURL = nil
                            } else {
                                var route = URLComponents(url: url, resolvingAgainstBaseURL: true)
                                route?.fragment = "/settings/meshcore"
                                if let destination = route?.url {
                                    meshcoreReturnURL = url
                                    self.url = destination
                                }
                            }
                        } label: {
                            Label(meshcoreReturnURL != nil ? "Messages" : "MeshCore",
                                  systemImage: meshcoreReturnURL != nil ? "bubble.left.and.bubble.right" : "dot.radiowaves.left.and.right")
                                .labelStyle(.iconOnly).frame(width: 44, height: 44)
                        }.accessibilityIdentifier("next-meshcore-settings")
                        Button("TCP connections") { panel = .connections }
                            .accessibilityIdentifier("tcp-connections")
                    }.padding(.horizontal)
                    if let address {
                        HStack {
                            Text("My LXMF address")
                            Spacer()
                            Button { panel = .myContact } label: {
                                Label("Show my contact QR code", systemImage: "qrcode").labelStyle(.iconOnly)
                            }
                            .accessibilityIdentifier("show-my-contact-qr")
                            ShareLink(item: address)
                        }
                        .padding(.horizontal)
                        Text(address).font(.caption.monospaced()).textSelection(.enabled)
                            .accessibilityIdentifier("my-lxmf-address")
                        Label(tcpConnected == true ? "Reticulum connected" : "No Reticulum connection",
                              systemImage: tcpConnected == true ? "link" : "link.badge.plus")
                            .font(.caption)
                            .padding(.vertical, 4)
                            .task(id: url) { await watchConnection(at: url) }
                    }
                    ProbeWebView(url: url, onExport: { file in
                        exportFolder = file.deletingLastPathComponent()
                        exportItem = NextExportItem(file: file)
                    }, onExportError: { problem in
                        exportError = problem; showExportError = true
                    }, onPreferencesError: { problem in
                        preferencesError = problem; showPreferencesError = true
                    })
                }
            } else if let error {
                VStack {
                    ContentUnavailableView("neXt couldn’t start", systemImage: "exclamationmark.triangle",
                                           description: Text(error))
                    Button("Review connection settings") { self.error = nil; starting = false }
                }
            } else if (simulator && !setupReviewFixture) || starting {
                ProgressView("Starting neXt…")
            } else {
                Form {
                    Section("Get started") {
                        Button("Review device permissions") { panel = .permissions }
                            .accessibilityIdentifier("next-setup-permission-checkup")
                    }
                    Section("Reticulum TCP connections") {
                        Text("\(configuredPeers.filter(\.enabled).count) enabled peers")
                        Button("Edit TCP connections") { panel = .connections }
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
        .onChange(of: scenePhase) { _, phase in
            appActive = phase == .active
            if appActive { Task { await alerts.refreshAuthorization() } }
        }
        .onChange(of: alerts.requestedAddress) { _, peer in
            if peer != nil { openRequestedConversation() }
        }
        .onChange(of: alerts.requestedMeshCoreKey) { _, key in
            if key != nil { openRequestedConversation() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .familyRadioData).receive(on: DispatchQueue.main)) { _ in
            radioWake?.received()
        }
        .sheet(item: $panel) { selected in
            switch selected {
            case .rnode:
                if let url { NextRNodeSettings(base: url).interactiveDismissDisabled() }
            case .alerts:
                NextMessageAlertSettings(alerts: alerts) {
                    guard let url else { throw URLError(.notConnectedToInternet) }
                    return try await Self.unreadMessages(at: url)
                } onPermissionCheckup: { panel = .permissions }
            case .permissions:
                NextPermissionCheckup(alerts: alerts) {
                    guard let url else { return [] }
                    return try await Self.unreadMessages(at: url)
                }
            case .connections:
                NextTCPConnections(base: url, initial: configuredPeers) { peers in
                    savedPeers = (try? NextTCPPeer.encodeSettings(peers)) ?? savedPeers
                }.interactiveDismissDisabled()
            case .myContact:
                NextMyContactQR(address: address ?? "")
            }
        }
        .sheet(item: $exportItem, onDismiss: {
            if let exportFolder { try? FileManager.default.removeItem(at: exportFolder) }
            exportFolder = nil
        }) { item in NextAttachmentExport(item: item) }
        .alert("Settings couldn’t be saved", isPresented: $showPreferencesError) {
            Button("OK", role: .cancel) {}
        } message: { Text(preferencesError) }
        .alert("Attachment couldn’t be saved", isPresented: $showExportError) {
            Button("OK", role: .cancel) { }
        } message: { Text(exportError) }
        .alert("Conversation unavailable", isPresented: Binding(
            get: { notificationRouteError != nil },
            set: { if !$0 { notificationRouteError = nil } }
        )) { Button("OK", role: .cancel) { notificationRouteError = nil } } message: { Text(notificationRouteError ?? "") }
        .task {
            guard url == nil, error == nil, !starting, !setupReviewFixture else { return }
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
                let (data, _) = try await NextHTTP.shared.data(for: request)
                let status = try JSONDecoder().decode(ConnectionStatus.self, from: data)
                tcpConnected = status.connected
                tcpEnabledCount = status.enabledCount
                theme = status.theme ?? "system"
            } catch {
                tcpConnected = nil
            }
            if let notices = try? await Self.unreadMessages(at: url) {
                await alerts.publish(notices, appActive: appActive)
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
            radioWake = FamilyRadioWake(begin: { expiration in
                let lease = UIApplication.shared.beginBackgroundTask(withName: "neXt radio inbox") {
                    Task { @MainActor in expiration() }
                }
                return lease == .invalid ? nil : lease.rawValue
            }, end: { UIApplication.shared.endBackgroundTask(UIBackgroundTaskIdentifier(rawValue: $0)) },
                now: { ProcessInfo.processInfo.systemUptime },
                active: { UIApplication.shared.applicationState == .active },
                refresh: {
                    if let notices = try? await Self.unreadMessages(at: result.url) {
                        await alerts.publish(notices, appActive: UIApplication.shared.applicationState == .active)
                    }
                }, pause: { try await Task.sleep(for: .seconds(1)) })
            openRequestedConversation()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func openRequestedConversation() {
        if let key = alerts.requestedMeshCoreKey, let current = url {
            guard !routingMeshCoreAlert else { return }
            routingMeshCoreAlert = true
            Task {
                defer { routingMeshCoreAlert = false }
                do {
                    guard var endpoint = URLComponents(url: current, resolvingAgainstBaseURL: true) else { throw URLError(.badURL) }
                    endpoint.path = "/api/v1/meshcore/notification-target"
                    endpoint.fragment = nil
                    endpoint.queryItems = [URLQueryItem(name: "key", value: key)]
                    guard let requestURL = endpoint.url else { throw URLError(.badURL) }
                    var request = URLRequest(url: requestURL)
                    request.timeoutInterval = 5
                    let (data, response) = try await NextHTTP.shared.data(for: request)
                    guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
                    struct Result: Decodable { let result: NextMeshCoreAlertTarget? }
                    let target = try JSONDecoder().decode(Result.self, from: data).result
                    guard let fragment = target?.fragment,
                          var destination = URLComponents(url: current, resolvingAgainstBaseURL: true) else { throw URLError(.badServerResponse) }
                    guard alerts.requestedMeshCoreKey == key else { return }
                    destination.fragment = fragment
                    if let routed = destination.url { url = routed }
                    alerts.consumedRoute()
                } catch {
                    if alerts.requestedMeshCoreKey == key {
                        notificationRouteError = "This MeshCore conversation is no longer available for the saved radio."
                        alerts.consumedRoute()
                    }
                }
            }
            return
        }
        guard let peer = alerts.requestedAddress, let current = url,
              var destination = URLComponents(url: current, resolvingAgainstBaseURL: false) else { return }
        destination.fragment = "/messages/" + peer
        if let routed = destination.url { url = routed; alerts.consumedRoute() }
    }

    private static func unreadMessages(at base: URL) async throws -> [NextUnreadNotice] {
        guard let endpoint = URL(string: "/api/v1/preview/unread-messages", relativeTo: base) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = 2
        let (data, response) = try await NextHTTP.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        struct Batch: Decodable { let messages: [NextUnreadNotice] }
        return try JSONDecoder().decode(Batch.self, from: data).messages
    }

    private static func start(_ settings: PeerSettings?) async throws -> (url: URL, address: String?) {
        guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        let modules = resources.appendingPathComponent("staged")
        let directory = try FileManager.default.url(
            for: .applicationSupportDirectory,
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
        next_probe_set_credentials { request in
            guard let request else { return nil }
            return strdup(NextCredentials.shared.request(String(cString: request)))
        }
        next_probe_set_sip { request in
            guard let request else { return nil }
            return strdup(NextSIPBridge.request(String(cString: request)))
        }
        next_probe_set_bluetooth { request in
            guard let request else { return nil }
            return strdup(FamilyBluetooth.shared.request(String(cString: request)))
        }
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
                let accessFile = directory.appendingPathComponent("next-runtime-info.json")
                try NextHTTP.shared.configure(Data(contentsOf: accessFile), for: url)
                return (url, try? String(contentsOf: address, encoding: .utf8))
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw URLError(.timedOut)
    }
}

@MainActor
private struct ProbeWebView: UIViewRepresentable {
    let url: URL
    let onExport: (URL) -> Void
    let onExportError: (String) -> Void
    let onPreferencesError: (String) -> Void

    func makeCoordinator() -> NavigationGuard { NavigationGuard(url: url, onExport: onExport, onError: onExportError, onPreferencesError: onPreferencesError) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        do { try context.coordinator.preferences.install(in: configuration) }
        catch { onPreferencesError("Your interface settings could not be restored. Please reopen neXt before changing them.") }
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
        if let request = try? NextHTTP.shared.webRequest(for: url) { view.load(request) }
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        // React only to an explicit native route request. Comparing view.url
        // itself would overwrite ordinary in-page navigation on every redraw.
        if context.coordinator.requestedURL != url {
            context.coordinator.requestedURL = url
            if let request = try? NextHTTP.shared.webRequest(for: url) { view.load(request) }
        }
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: NavigationGuard) {
        coordinator.downloads.cancel()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "nextPreferences", contentWorld: .page)
    }

    @MainActor
    final class NavigationGuard: NSObject, WKNavigationDelegate {
        let url: URL
        let preferences: NextWebPreferencesBridge
        let downloads: NextAttachmentDownloads
        var requestedURL: URL
        init(url: URL, onExport: @escaping (URL) -> Void, onError: @escaping (String) -> Void, onPreferencesError: @escaping (String) -> Void) {
            self.url = url
            requestedURL = url
            preferences = NextWebPreferencesBridge(base: url, folder: FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]) {
                onPreferencesError("Your interface settings could not be saved. Please try again before closing neXt.")
            }
            downloads = NextAttachmentDownloads(base: url, onComplete: onExport, onError: onError)
            super.init()
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // Log only the local access result, never credentials or message data.
            webView.callAsyncJavaScript("return (await fetch('/api/v1/status', {cache:'no-store'})).status",
                                        arguments: [:], in: nil, in: .page) { result in
                switch result {
                case .success(let value):
                    if let status = value as? Int, status != 200 {
                        print("neXt local WebView access status: \(status)")
                    }
                case .failure:
                    print("neXt local WebView access check unavailable")
                }
            }
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
            downloads.start(download)
        }

        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
            downloads.start(download)
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            let target = action.request.url
            if action.shouldPerformDownload {
                decisionHandler(downloads.allows(target) ? .download : .cancel)
            } else {
                decisionHandler(action.targetFrame?.isMainFrame == true && downloads.isLocal(target) ? .allow : .cancel)
            }
        }
    }
}
