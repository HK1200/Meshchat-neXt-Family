import SwiftUI
import WebKit

@main
struct ProbeApp: App {
    @UIApplicationDelegateAdaptor(NextMessageAlerts.self) private var alerts
    init() { alerts.callAlertsLaunch = { NextCallWakeOwner.shared.restore() } }
    var body: some Scene {
        WindowGroup { ProbeScreen(alerts: alerts) }
    }
}

private struct PeerSettings: Encodable {
    let host: String
    let port: Int
    let address: String
    let peers: [NextTCPPeer]
    let notification_floor: Int
}

private struct ProbeScreen: View {
    @ObservedObject var alerts: NextMessageAlerts
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @State private var appActive = true
    private enum Panel: String, Identifiable {
        case alerts, rnode, connections, myContact, permissions, sip, mailbox, reticulum, calling, location, callAlerts
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
    @State private var pushSyncing = false
    @State private var lastPushCheck = ContinuousClock.now - .seconds(15)
    @StateObject private var webLoad = NextWebLoadState()
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
        return PeerSettings(host: host, port: Int(port) ?? 4343, address: contact.lowercased(), peers: configuredPeers,
                            notification_floor: alerts.reticulumBaselineID)
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
                        Button { panel = .calling } label: {
                            Label("Calling", systemImage: "phone").labelStyle(.iconOnly).frame(width: 44, height: 44)
                        }.accessibilityIdentifier("next-calling-menu")
                        Button { panel = .connections } label: {
                            Label("TCP connections", systemImage: "network")
                                .labelStyle(.iconOnly).frame(width: 44, height: 44)
                        }.accessibilityIdentifier("tcp-connections")
                    }.padding(.horizontal)
                    if let address {
                        HStack {
                            Button { panel = .mailbox } label: {
                                Label("Offline mailbox", systemImage: "tray.and.arrow.down")
                                    .labelStyle(.iconOnly)
                                    .frame(width: 44, height: 44)
                                    .contentShape(Rectangle())
                            }.accessibilityIdentifier("next-mailbox-settings")
                            Button { panel = .location } label: {
                                Label("Location sharing", systemImage: "location")
                                    .labelStyle(.iconOnly).frame(width: 44, height: 44)
                            }.accessibilityIdentifier("next-location-settings")
                            Text("My LXMF address")
                                .font(.caption).lineLimit(1)
                            Spacer()
                            Button { panel = .myContact } label: {
                                Label("Show my contact QR code", systemImage: "qrcode")
                                    .labelStyle(.iconOnly)
                                    .frame(width: 44, height: 44)
                                    .contentShape(Rectangle())
                            }
                            .accessibilityIdentifier("show-my-contact-qr")
                            ShareLink(item: address) {
                                Label("Share my LXMF address", systemImage: "square.and.arrow.up")
                                    .labelStyle(.iconOnly).frame(width: 44, height: 44)
                            }.accessibilityIdentifier("share-my-lxmf-address")
                        }
                        .padding(.horizontal)
                        Text(address).font(.caption.monospaced()).textSelection(.enabled)
                            .accessibilityIdentifier("my-lxmf-address")
                            .accessibilityValue(webLoad.accessibilityValue)
                        Label(tcpConnected == true ? "Reticulum connected" : "No Reticulum connection",
                              systemImage: tcpConnected == true ? "link" : "link.badge.plus")
                            .font(.caption)
                            .padding(.vertical, 4)
                            .task(id: url) { await watchConnection(at: url) }
                    }
                    ProbeWebView(url: url, modalPresented: panel != nil, loadState: webLoad, onExport: { file in
                        exportFolder = file.deletingLastPathComponent()
                        exportItem = NextExportItem(file: file)
                    }, onExportError: { problem in
                        exportError = problem; showExportError = true
                    }, onPreferencesError: { problem in
                        preferencesError = problem; showPreferencesError = true
                    }, onExternalLink: { target in openURL(target) })
                    .overlay {
                        if let problem = webLoad.problem {
                            VStack(spacing: 12) {
                                Text(problem).multilineTextAlignment(.center)
                                Button("Retry interface") { webLoad.retry() }
                                    .accessibilityIdentifier("next-web-retry")
                            }
                            .padding().frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(.background)
                            .accessibilityIdentifier("next-web-error")
                        } else if webLoad.loading {
                            ProgressView("Loading interface…")
                                .frame(maxWidth: .infinity, maxHeight: .infinity)
                                .background(.background)
                                .accessibilityIdentifier("next-web-loading")
                        }
                    }
                }
            } else if let error {
                VStack {
                    ContentUnavailableView("neXt couldn’t start", systemImage: "exclamationmark.triangle",
                                           description: Text(error))
                    Text("Close and reopen neXt before trying to start it again.")
                        .font(.callout)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
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
        // The native sheet owns accessibility while it is presented. Apply
        // this at the SwiftUI container as well as WKWebView: WebKit exposes
        // its remote accessibility tree independently of UIKit descendants.
        .accessibilityHidden(panel != nil || exportItem != nil)
        .preferredColorScheme(theme == "dark" ? .dark : theme == "light" ? .light : nil)
        .onChange(of: scenePhase) { _, phase in
            appActive = phase == .active
            if appActive {
                next_probe_request_listener_recovery()
                Task { await alerts.refreshAuthorization() }
                NextCallWakeOwner.shared.refreshPermissions()
            }
        }
        .onChange(of: alerts.mailboxInboxRequested) { _, wanted in
            if wanted { openMailboxInbox() }
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
            case .calling:
                NavigationStack {
                    List {
                        Button { panel = .reticulum } label: {
                            Label("Reticulum calling", systemImage: "antenna.radiowaves.left.and.right")
                                .frame(minHeight: 44)
                        }.accessibilityIdentifier("next-reticulum-calling")
                        Button { panel = .sip } label: {
                            Label("SIP accounts", systemImage: "phone")
                                .frame(minHeight: 44)
                        }.accessibilityIdentifier("next-sip-settings")
                        Button { panel = .callAlerts } label: {
                            Label("Incoming call alerts", systemImage: "phone.badge.waveform")
                                .frame(minHeight: 44)
                        }.accessibilityIdentifier("next-call-alert-settings")
                    }
                    .navigationTitle("Calling")
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) { Button("Done") { panel = nil } }
                    }
                }
            case .callAlerts:
                if let url { NextCallWakeSettings(base: url, registration: NextCallWakeOwner.shared.registration) }
            case .location:
                if let url { NextLocationSettings(base: url).interactiveDismissDisabled() }
            case .mailbox:
                if let url { NextMailboxSettings(base: url, push: alerts.push).interactiveDismissDisabled() }
            case .reticulum:
                if let url { NextReticulumSettings(base: url).interactiveDismissDisabled() }
            case .sip:
                if let url { NextSIPSettings(base: url).interactiveDismissDisabled() }
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
                NextMyContactQR(address: address ?? "", base: url)
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
        var lastRecovery = ContinuousClock.now - .seconds(15)
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
                if appActive, !Task.isCancelled, lastRecovery.duration(to: ContinuousClock.now) >= .seconds(15) {
                    next_probe_request_listener_recovery()
                    lastRecovery = ContinuousClock.now
                }
            }
            if alerts.push.configured || alerts.push.busy {
                await refreshPushState(at: url)
            }
            if !alerts.push.configured || alerts.push.stopping {
                alerts.consumedMailboxSync(through: alerts.mailboxSyncGeneration)
            } else if alerts.mailboxSyncRequested && !pushSyncing {
                Task { await retrievePushMailbox(at: url) }
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

    @MainActor private func refreshPushState(at base: URL) async {
        do {
            let endpoint = URL(string: "/api/v1/preview/push-enrollment-state", relativeTo: base)!
            let (data, response) = try await NextHTTP.shared.data(from: endpoint)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return }
            alerts.push.refresh(try JSONDecoder().decode(NextPushState.self, from: data))
        } catch { /* Keep enrollment/revocation pending while the local listener recovers. */ }
    }

    @MainActor private func retrievePushMailbox(at base: URL) async {
        guard alerts.push.configured, !alerts.push.stopping, !pushSyncing,
              lastPushCheck.duration(to: ContinuousClock.now) >= .seconds(15) else { return }
        pushSyncing = true; lastPushCheck = .now
        defer { pushSyncing = false }
        let generation = alerts.mailboxSyncGeneration
        do {
            struct Token: Decodable { let csrf_token: String }
            let (tokenData, tokenResponse) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/auth/csrf", relativeTo: base)!)
            guard (tokenResponse as? HTTPURLResponse)?.statusCode == 200 else { return }
            let token = try JSONDecoder().decode(Token.self, from: tokenData)
            let endpoint = URL(string: "/api/v1/preview/mailbox/sync", relativeTo: base)!
            var request = URLRequest(url: endpoint); request.httpMethod = "POST"; request.timeoutInterval = 15
            request.setValue(token.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
            var origin = URLComponents(url: base, resolvingAgainstBaseURL: true)!
            origin.path = ""; origin.query = nil; origin.fragment = nil
            request.setValue(origin.string, forHTTPHeaderField: "Origin")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
            let (data, response) = try await NextHTTP.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return }
            var state = try JSONDecoder().decode(NextMailboxState.self, from: data)
            for _ in 0..<45 {
                guard !Task.isCancelled, alerts.push.configured, !alerts.push.stopping else { return }
                if state.status == "complete" || state.status == "off" {
                    alerts.consumedMailboxSync(through: generation)
                    lastPushCheck = .now - .seconds(15)
                    return
                }
                if state.status == "failed" { return }
                try await Task.sleep(for: .seconds(1))
                let (fresh, result) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/preview/mailbox", relativeTo: base)!)
                guard (result as? HTTPURLResponse)?.statusCode == 200 else { return }
                state = try JSONDecoder().decode(NextMailboxState.self, from: fresh)
            }
        } catch { /* The generation stays pending for a bounded retry after reconnect. */ }
    }

    private func launch(_ settings: PeerSettings?) async {
        do {
            let configuration = try settings.map { try JSONEncoder().encode($0) }
            let result = try await NextRuntimeLauncher.shared.session(configuration: configuration)
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
            if alerts.mailboxInboxRequested { openMailboxInbox() }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func openMailboxInbox() {
        guard alerts.mailboxInboxRequested, let current = url,
              var destination = URLComponents(url: current, resolvingAgainstBaseURL: false) else { return }
        destination.fragment = "/messages"
        guard let routed = destination.url else { return }
        panel = nil; meshcoreReturnURL = nil; url = routed
        alerts.consumedMailboxInbox()
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
                    if let routed = destination.url { panel = nil; url = routed }
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
        if let routed = destination.url { panel = nil; url = routed; alerts.consumedRoute() }
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


}

@MainActor
private struct ProbeWebView: UIViewRepresentable {
    let url: URL
    let modalPresented: Bool
    @ObservedObject var loadState: NextWebLoadState
    let onExport: (URL) -> Void
    let onExportError: (String) -> Void
    let onPreferencesError: (String) -> Void
    let onExternalLink: (URL) -> Void

    func makeCoordinator() -> NavigationGuard { NavigationGuard(url: url, loadState: loadState, onExport: onExport, onError: onExportError, onPreferencesError: onPreferencesError, onExternalLink: onExternalLink) }

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
        configuration.userContentController.addUserScript(
            WKUserScript(source: NextModalPage.loadingScript, injectionTime: .atDocumentStart,
                         forMainFrameOnly: true, in: .defaultClient)
        )
        let view = WKWebView(frame: .zero, configuration: configuration)
        #if DEBUG
        // Explicit, per-launch development opt-in. The device must separately
        // permit Apple's Web Inspector; this cannot bypass that setting.
        if #available(iOS 16.4, *), ProcessInfo.processInfo.arguments.contains("--inspect-web-interface") {
            view.isInspectable = true
        }
        #endif
        view.accessibilityElementsHidden = modalPresented || loadState.loading || loadState.problem != nil
        view.navigationDelegate = context.coordinator
        context.coordinator.setModal(modalPresented, on: view)
        context.coordinator.load(url, in: view)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        // A presented native form owns interaction; keep its inactive WebKit
        // page out of VoiceOver and accessibility snapshots until dismissal.
        view.accessibilityElementsHidden = modalPresented || loadState.loading || loadState.problem != nil
        context.coordinator.setModal(modalPresented, on: view)
        // React only to an explicit native route request. Comparing view.url
        // itself would overwrite ordinary in-page navigation on every redraw.
        if context.coordinator.requestedURL != url || context.coordinator.handledRetry != loadState.retryRequest {
            context.coordinator.requestedURL = url
            context.coordinator.handledRetry = loadState.retryRequest
            context.coordinator.load(url, in: view)
        }
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: NavigationGuard) {
        coordinator.cancelLoadWatchdog()
        coordinator.downloads.cancel()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "nextPreferences", contentWorld: .page)
    }

    @MainActor
    final class NavigationGuard: NSObject, WKNavigationDelegate {
        let url: URL
        let onExternalLink: (URL) -> Void
        let preferences: NextWebPreferencesBridge
        let downloads: NextAttachmentDownloads
        var requestedURL: URL
        private var modalPresented = false
        private var appliedPageSuppression: Bool?
        let loadState: NextWebLoadState
        var handledRetry = 0
        private var loadWatchdog: Task<Void, Never>?
        private var currentNavigation: WKNavigation?
        private var renderWait: Task<Void, Never>?
        private var loadRequest = 0

        func cancelLoadWatchdog() {
            loadRequest += 1
            loadWatchdog?.cancel(); loadWatchdog = nil
            renderWait?.cancel(); renderWait = nil
        }

        func load(_ target: URL, in view: WKWebView) {
            cancelLoadWatchdog()
            let expected = loadRequest
            view.accessibilityElementsHidden = true
            // Do not publish ObservableObject changes during updateUIView.
            Task { @MainActor [weak self, weak view] in
                guard let self, let view, self.loadRequest == expected else { return }
                let generation = self.loadState.begin()
                guard let request = try? NextHTTP.shared.webRequest(for: target) else {
                    self.loadState.failed(generation); return
                }
                self.currentNavigation = view.load(request)
                self.loadWatchdog = Task { @MainActor [weak self, weak view] in
                    do { try await Task.sleep(for: .seconds(45)) } catch { return }
                    guard let self, let view, !Task.isCancelled else { return }
                    self.recoverStalledStartup(generation, in: view)
                }
            }
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            guard let navigation, navigation !== currentNavigation else { return }
            // A page-initiated local reload also needs the native fallback.
            cancelLoadWatchdog()
            currentNavigation = navigation
            let generation = loadState.begin()
            webView.accessibilityElementsHidden = true
            loadWatchdog = Task { @MainActor [weak self, weak webView] in
                do { try await Task.sleep(for: .seconds(45)) } catch { return }
                guard let self, let webView, !Task.isCancelled else { return }
                self.recoverStalledStartup(generation, in: webView)
            }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            navigationFailed(navigation)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            navigationFailed(navigation)
        }

        private func navigationFailed(_ navigation: WKNavigation?) {
            guard let navigation, navigation === currentNavigation else { return }
            cancelLoadWatchdog()
            loadState.failed(loadState.generation)
        }

        func setModal(_ active: Bool, on view: WKWebView) {
            modalPresented = active
            let suppressed = active || loadState.loading || loadState.problem != nil
            guard appliedPageSuppression != suppressed else { return }
            applyModal(to: view)
        }

        private func applyModal(to view: WKWebView) {
            // The isolated content world prevents page scripts from changing
            // the saved pre-modal accessibility state. DOM attributes remain
            // visible to WebKit's own accessibility and input systems.
            let suppressed = modalPresented || loadState.loading || loadState.problem != nil
            appliedPageSuppression = suppressed
            view.callAsyncJavaScript(NextModalPage.script, arguments: ["active": suppressed],
                                     in: nil, in: .defaultClient) { _ in }
        }
        init(url: URL, loadState: NextWebLoadState, onExport: @escaping (URL) -> Void, onError: @escaping (String) -> Void, onPreferencesError: @escaping (String) -> Void, onExternalLink: @escaping (URL) -> Void) {
            self.url = url
            self.loadState = loadState
            self.onExternalLink = onExternalLink
            requestedURL = url
            preferences = NextWebPreferencesBridge(base: url, folder: FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]) {
                onPreferencesError("Your interface settings could not be saved. Please try again before closing neXt.")
            }
            downloads = NextAttachmentDownloads(base: url, onComplete: onExport, onError: onError)
            super.init()
        }

        private func recoverStalledStartup(_ generation: Int, in view: WKWebView) {
            guard loadState.startupStalled(generation) else { return }
            // Retry only the native-authorized local route. Keep the backend,
            // saved messages and connections, and never loop indefinitely.
            load(requestedURL, in: view)
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            // Recreate WebKit's renderer without restarting Python or losing
            // saved conversations. Restore only our authenticated local URL.
            let current = webView.url
            let target = current?.scheme == url.scheme && current?.host == url.host && current?.port == url.port ? current! : requestedURL
            cancelLoadWatchdog()
            guard loadState.rendererTerminated() else { return }
            load(target, in: webView)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard let navigation, navigation === currentNavigation else { return }
            let generation = loadState.generation
            renderWait?.cancel()
            renderWait = Task { @MainActor [weak self, weak webView] in
                for _ in 0..<120 {
                    guard let self, let webView, !Task.isCancelled,
                          self.loadState.generation == generation else { return }
                    let rendered: Bool = await withCheckedContinuation { continuation in
                        webView.callAsyncJavaScript(NextWebLoadState.pageReadyScript, arguments: [:], in: nil, in: .page) { result in
                            continuation.resume(returning: (try? result.get()) as? Bool ?? false)
                        }
                    }
                    guard !Task.isCancelled, self.loadState.generation == generation else { return }
                    if rendered {
                        self.loadWatchdog?.cancel(); self.loadWatchdog = nil
                        self.loadState.ready(generation)
                        webView.accessibilityElementsHidden = self.modalPresented
                        self.applyModal(to: webView)
                        return
                    }
                    do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
                }
                guard let self, let webView else { return }
                self.recoverStalledStartup(generation, in: webView)
            }
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
            #if DEBUG
            if action.shouldPerformDownload || target?.scheme == "blob" {
                print("neXt export navigation: scheme=\(target?.scheme ?? "none") requested=\(action.shouldPerformDownload)")
            }
            #endif
            if action.shouldPerformDownload {
                decisionHandler(downloads.allows(target) ? .download : .cancel)
            } else if downloads.isLocal(target) {
                let ownSandbox = action.targetFrame?.isMainFrame == false &&
                    NextNomadFramePolicy.allows(target, base: downloads.base)
                decisionHandler(action.targetFrame?.isMainFrame == true || ownSandbox ? .allow : .cancel)
            } else if NextExternalLinks.allows(target, userActivated: action.navigationType == .linkActivated), let target {
                // Pass only the URL to the system browser. Never forward the
                // app's authenticated URLRequest, cookies or session headers.
                decisionHandler(.cancel)
                onExternalLink(target)
            } else {
                decisionHandler(.cancel)
            }
        }
    }
}
