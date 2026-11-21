import SwiftUI
import UIKit
import UserNotifications

struct NextUnreadNotice: Codable, Equatable {
    let id: Int
    let hash: String
    let peer: String
    var isValid: Bool {
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
        content.threadIdentifier = "next.contact." + notice.peer
        content.userInfo = ["peer": notice.peer, "message": notice.hash]
        try await UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "next.message." + notice.peer, content: content, trigger: nil)
        )
    }
}

@MainActor
final class NextMessageAlerts: NSObject, ObservableObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    @Published private(set) var authorization: UNAuthorizationStatus = .notDetermined
    @Published private(set) var requestedAddress: String?
    private let center: any NextAlertPosting
    private let defaults: UserDefaults
    private let ledgerKey = "next.notifiedMessageIDs.v1"
    private let baselineKey = "next.notificationBaselineID.v1"
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
                defaults.set(max(defaults.integer(forKey: baselineKey), valid.map(\.id).max() ?? 0), forKey: baselineKey)
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
        for notice in notices where notice.isValid && notice.id > defaults.integer(forKey: baselineKey) && !known.contains(notice.hash) {
            do {
                try await center.post(notice)
                known.insert(notice.hash)
                remember([notice.hash])
            } catch {
                // Retry on the next refresh; never mark an OS-rejected alert delivered.
            }
        }
    }

    func routeMessage(hash: String, peer: String) {
        let notice = NextUnreadNotice(id: 1, hash: hash, peer: peer)
        if notice.isValid { requestedAddress = peer }
    }
    func consumedRoute() { requestedAddress = nil }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                           didReceive response: UNNotificationResponse) async {
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier,
              let hash = response.notification.request.content.userInfo["message"] as? String,
              let peer = response.notification.request.content.userInfo["peer"] as? String else { return }
        await routeMessage(hash: hash, peer: peer)
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
                    Text("iOS may pause neXt after you switch apps or lock the screen. Notifications cannot arrive while it is paused. This preview does not yet provide suspended-delivery alerts.")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Message alerts")
            .task(id: scenePhase) { if scenePhase == .active { await alerts.refreshAuthorization() } }
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
