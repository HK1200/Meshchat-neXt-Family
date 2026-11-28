// SPDX-License-Identifier: 0BSD
import Foundation
import UIKit

/// Owns radio inbox processing independently of the visible web interface.
@MainActor
final class NextRadioInboxOwner {
    static let shared = NextRadioInboxOwner()
    private var inbox: FamilyRadioInbox?

    func install(alerts: NextMessageAlerts, restoring identifiers: [String]?) {
        if inbox == nil {
            let wake = FamilyRadioWake(begin: { expiration in
                let lease = UIApplication.shared.beginBackgroundTask(withName: "neXt radio inbox") {
                    Task { @MainActor in expiration() }
                }
                return lease == .invalid ? nil : lease.rawValue
            }, end: { UIApplication.shared.endBackgroundTask(UIBackgroundTaskIdentifier(rawValue: $0)) },
                now: { ProcessInfo.processInfo.systemUptime },
                active: { UIApplication.shared.applicationState == .active },
                prepare: { [weak alerts] in
                    await alerts?.refreshAuthorization()
                    // A slow cold start must not hold the wake indefinitely or
                    // cancel the process-wide runtime needed by the next screen.
                    _ = try? await NextRuntimeLauncher.shared.callWakeSession()
                }, refresh: { [weak alerts] in
                    guard let alerts,
                          let session = try? await NextRuntimeLauncher.shared.callWakeSession(),
                          let notices = try? await Self.unreadMessages(at: session.url) else { return }
                    await alerts.publish(notices, appActive: UIApplication.shared.applicationState == .active)
                }, pause: { try await Task.sleep(for: .seconds(1)) })
            inbox = FamilyRadioInbox(wake: wake)
        }
        if FamilyBluetooth.restoreForSystemLaunch(identifiers) { inbox?.restored() }
    }

    static func unreadMessages(at base: URL) async throws -> [NextUnreadNotice] {
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
