import Combine
import Foundation

/// Process-owned observations also work when iOS relaunches into the background
/// before there is a SwiftUI screen. The existing wake owns the bounded lease.
@MainActor
final class FamilyRadioInbox {
    private var observations: [AnyCancellable] = []
    private let wake: FamilyRadioWake
    private var stopped = false

    init(wake: FamilyRadioWake, center: NotificationCenter = .default) {
        self.wake = wake
        for event in [Notification.Name.familyRadioData, .familyRadioRestored, .familyInboxData] {
            observations.append(center.publisher(for: event).sink { [weak self] _ in
                Task { @MainActor [weak self] in self?.restored() }
            })
        }
    }
    func restored() { if !stopped { wake.received() } }
    func stop() { stopped = true; observations.removeAll(); wake.stop() }
}
