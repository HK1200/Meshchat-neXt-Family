import UIKit
import UserNotifications

@MainActor
final class FamilyNotifications: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    private let center = UNUserNotificationCenter.current()
    private let defaults = UserDefaults.standard
    private let ledgerKey = "family.notifiedMessageIDs"
    private var processing = false
    private var pendingOpen: (Int, String)?
    var openMessage: ((Int, String) -> Void)? {
        didSet {
            if let openMessage, let (contactID, messageID) = pendingOpen {
                pendingOpen = nil
                openMessage(contactID, messageID)
            }
        }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier,
              let contactID = response.notification.request.content.userInfo["contactId"] as? Int else { return }
        let messageID = response.notification.request.identifier
        await routeMessage(contactID, messageID)
    }

    private func routeMessage(_ contactID: Int, _ messageID: String) {
        if let openMessage { openMessage(contactID, messageID) }
        else { pendingOpen = (contactID, messageID) }
    }


    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        center.delegate = self
        return true
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    func isAuthorized() async -> Bool {
        let settings = await center.notificationSettings()
        return [.authorized, .provisional, .ephemeral].contains(settings.authorizationStatus)
    }

    func authorize(existingMessages: [FamilyMessage]) async throws -> Bool {
        let alreadyAuthorized = await isAuthorized()
        let granted = try await center.requestAuthorization(options: [.alert, .sound])
        if granted && !alreadyAuthorized {
            let existing = existingMessages.filter(\.incoming).map(\.id)
            let ids = defaults.stringArray(forKey: ledgerKey) ?? []
            defaults.set(Array((ids + existing).suffix(1000)), forKey: ledgerKey)
        }
        return granted
    }

    #if DEBUG
    func hasDeliveredMessage(from messages: [FamilyMessage]) async -> Bool {
        let incomingIDs = Set(messages.filter(\.incoming).map(\.id))
        let delivered = await center.deliveredNotifications()
        return delivered.contains { incomingIDs.contains($0.request.identifier) }
    }
    #endif

    func publish(_ conversations: [String: [FamilyMessage]]) async {
        guard !processing else { return }
        processing = true
        defer { processing = false }

        var ids = defaults.stringArray(forKey: ledgerKey) ?? []
        var known = Set(ids)
        for (key, messages) in conversations {
            guard let contactID = Int(key) else { continue }
            for message in messages where message.incoming && message.read != true && !known.contains(message.id) {
                let content = UNMutableNotificationContent()
                content.title = "New Family message"
                content.body = "Open neXt Family to read it."
                content.userInfo = ["contactId": contactID]
                content.sound = .default
                let request = UNNotificationRequest(identifier: message.id, content: content, trigger: nil)
                do {
                    try await center.add(request)
                    known.insert(message.id)
                    ids.append(message.id)
                    defaults.set(Array(ids.suffix(1000)), forKey: ledgerKey)
                } catch {
                    // A subsequent refresh can retry a notification the system did not accept.
                }
            }
        }
    }
}
