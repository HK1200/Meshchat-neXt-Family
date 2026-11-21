import SwiftUI
import UIKit
import UserNotifications

struct NextUnreadNotice: Codable, Equatable {
    let id: Int
    let hash: String
    let peer: String
    var meshcoreKey: String? = nil
    var isValid: Bool {
        (meshcoreKey == nil || (meshcoreKey?.utf8.count == 73 &&
            meshcoreKey?.range(of: "^meshcore-[a-f0-9]{64}$", options: .regularExpression) != nil)) &&
        id > 0 && hash.utf8.count == 64 && peer.utf8.count == 32 &&
        hash.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil &&
        peer.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil
    }
}

@MainActor
protocol NextAlertPosting {
    func authorization() async -> UNAuthorizationStatus
    func requestAuthorization() async throws -> Bool
    func post(_ notice: NextUnreadNotice) async throws
}

@MainActor
private struct NextSystemAlerts: NextAlertPosting {
    func authorization() async -> UNAuthorizationStatus {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return settings.authorizationStatus
    }
    func requestAuthorization() async throws -> Bool {
        try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
    }
    func post(_ notice: NextUnreadNotice) async throws {
        let content = UNMutableNotificationContent()
        content.title = "New neXt message"
        content.body = "Open Meshchat neXt to read it."
        content.sound = .default
        content.threadIdentifier = "next.contact." + (notice.meshcoreKey ?? notice.peer)
        content.userInfo = ["peer": notice.peer, "message": notice.hash]
        if let key = notice.meshcoreKey { content.userInfo["meshcore"] = key }
        try await UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "next.message." + (notice.meshcoreKey ?? notice.peer), content: content, trigger: nil)
        )
    }
}

@MainActor
final class NextMessageAlerts: NSObject, ObservableObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    @Published private(set) var authorization: UNAuthorizationStatus = .notDetermined
    @Published private(set) var requestedAddress: String?
    @Published private(set) var requestedMeshCoreKey: String?
    private let center: any NextAlertPosting
    private let defaults: UserDefaults
    private let ledgerKey = "next.notifiedMessageIDs.v1"
    private let baselineKey = "next.notificationBaselineID.v1"
    private let meshcoreBaselineKey = "next.meshcoreNotificationBaselineID.v1"
    private var processing = false
    private var authorizing = false

    override init() {
        center = NextSystemAlerts()
        defaults = .standard
        super.init()
    }
    init(center: any NextAlertPosting, defaults: UserDefaults) {
        self.center = center; self.defaults = defaults
        super.init()
    }
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }
    var enabled: Bool { [.authorized, .provisional, .ephemeral].contains(authorization) }
    func refreshAuthorization() async { authorization = await center.authorization() }

    func authorize(existing: [NextUnreadNotice]) async throws {
        guard !authorizing else { return }
        authorizing = true
        defer { authorizing = false }
        await refreshAuthorization()
        let previouslyEnabled = enabled
        if try await center.requestAuthorization() {
            if !previouslyEnabled {
                let valid = existing.filter(\.isValid)
                let reticulum = valid.filter { $0.meshcoreKey == nil }
                let meshcore = valid.filter { $0.meshcoreKey != nil }
                defaults.set(max(defaults.integer(forKey: baselineKey), reticulum.map(\.id).max() ?? 0), forKey: baselineKey)
                defaults.set(max(defaults.integer(forKey: meshcoreBaselineKey), meshcore.map(\.id).max() ?? 0), forKey: meshcoreBaselineKey)
                remember(valid.map(\.hash))
            }
        }
        await refreshAuthorization()
    }

    private func remember(_ additional: [String]) {
        var seen = Set<String>()
        let newestFirst = ((defaults.stringArray(forKey: ledgerKey) ?? []) + additional).reversed()
        let unique = newestFirst.filter { seen.insert($0).inserted }.prefix(2000)
        defaults.set(Array(unique.reversed()), forKey: ledgerKey)
    }

    func publish(_ notices: [NextUnreadNotice], appActive: Bool) async {
        guard !processing, !authorizing, !appActive else { return }
        processing = true
        defer { processing = false }
        await refreshAuthorization()
        guard enabled, !authorizing else { return }
        var known = Set(defaults.stringArray(forKey: ledgerKey) ?? [])
        for notice in notices where notice.isValid && notice.id > defaults.integer(forKey: notice.meshcoreKey == nil ? baselineKey : meshcoreBaselineKey) && !known.contains(notice.hash) {
            do {
                try await center.post(notice)
                known.insert(notice.hash)
                remember([notice.hash])
            } catch {
                // Retry on the next refresh; never mark an OS-rejected alert delivered.
            }
        }
    }

    func routeMessage(hash: String, peer: String, meshcoreKey: String? = nil) {
        let notice = NextUnreadNotice(id: 1, hash: hash, peer: peer, meshcoreKey: meshcoreKey)
        if notice.isValid {
            requestedAddress = meshcoreKey == nil ? peer : nil
            requestedMeshCoreKey = meshcoreKey
        }
    }
    func consumedRoute() { requestedAddress = nil; requestedMeshCoreKey = nil }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                           didReceive response: UNNotificationResponse) async {
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier,
              let hash = response.notification.request.content.userInfo["message"] as? String,
              let peer = response.notification.request.content.userInfo["peer"] as? String else { return }
        let rawKey = response.notification.request.content.userInfo["meshcore"]
        if rawKey != nil && !(rawKey is String) { return }
        await routeMessage(hash: hash, peer: peer, meshcoreKey: rawKey as? String)
    }
}

struct NextMessageAlertSettings: View {
    @ObservedObject var alerts: NextMessageAlerts
    let existing: () async throws -> [NextUnreadNotice]
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL
    @Environment(\.dismiss) private var dismiss
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Message alerts") {
                    Text("Show a private alert when neXt receives an unread message while the app is not in front. Names and message text stay off the notification.")
                    LabeledContent("Notifications", value: alerts.enabled ? "Enabled" : "Not enabled")
                    if alerts.authorization == .notDetermined {
                        Button("Allow message alerts") {
                            busy = true
                            Task {
                                defer { busy = false }
                                do {
                                    let baseline = try await existing()
                                    try await alerts.authorize(existing: baseline)
                                }
                                catch { self.error = "Message alerts could not be prepared. Check that neXt is connected and try again." }
                            }
                        }.disabled(busy)
                    } else {
                        Button("Open neXt settings") {
                            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                        }
                    }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
                Section("When iOS pauses the app") {
                    Text("iOS may pause neXt after you switch apps or lock the screen. A connected Bluetooth radio can wake it when iOS permits. Internet-only alerts while fully suspended are not yet supported.")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Message alerts")
            .task(id: scenePhase) { if scenePhase == .active { await alerts.refreshAuthorization() } }
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
