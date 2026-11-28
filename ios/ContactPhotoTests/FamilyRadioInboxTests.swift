import XCTest
@testable import FamilyLive

@MainActor
final class FamilyRadioInboxTests: XCTestCase {
    private var begun = 0
    private var refreshed = 0
    private var ended: [Int] = []
    private var foreground = false
    private var expiration: FamilyRadioWake.Expiration?
    private var gate: CheckedContinuation<Void, Never>?
    private func makeWake() -> FamilyRadioWake {
        FamilyRadioWake(begin: { callback in
            self.begun += 1; self.expiration = callback; return self.begun
        }, end: { self.ended.append($0) }, now: { 0 }, active: { self.foreground },
        refresh: { self.refreshed += 1; await withCheckedContinuation { self.gate = $0 } },
        pause: { try await Task.sleep(for: .seconds(1)) })
    }
    private func settle(_ condition: () -> Bool) async {
        let end = ContinuousClock.now.advanced(by: .seconds(5))
        while !condition(), ContinuousClock.now < end { await Task.yield() }
        XCTAssertTrue(condition())
    }
    private func finish(_ owner: FamilyRadioInbox) {
        owner.stop(); gate?.resume(); gate = nil
    }
    func testRestoredRadioStartsColdInboxWithoutAnyScreen() async {
        let center = NotificationCenter(), wake = makeWake()
        let owner = FamilyRadioInbox(wake: wake, center: center)
        center.post(name: .familyRadioRestored, object: nil)
        await settle { self.refreshed == 1 }
        XCTAssertEqual(begun, 1); XCTAssertTrue(wake.isRunning)
        finish(owner); XCTAssertEqual(ended, [1])
    }
    func testRadioAndVerifiedInboxBurstsShareOneBackgroundLease() async {
        let center = NotificationCenter(), wake = makeWake()
        let owner = FamilyRadioInbox(wake: wake, center: center)
        for event in [Notification.Name.familyRadioData, .familyInboxData, .familyRadioRestored] {
            center.post(name: event, object: nil)
        }
        await settle { self.refreshed == 1 }
        XCTAssertEqual(begun, 1)
        finish(owner); XCTAssertEqual(ended, [1])
    }
    func testStoppedOwnerRejectsEvenAlreadyQueuedSystemEvents() async {
        let center = NotificationCenter(), wake = makeWake()
        let owner = FamilyRadioInbox(wake: wake, center: center)
        center.post(name: .familyRadioRestored, object: nil)
        owner.stop(); owner.restored()
        center.post(name: .familyRadioData, object: nil)
        for _ in 0..<20 { await Task.yield() }
        XCTAssertEqual(begun, 0); XCTAssertEqual(refreshed, 0)
    }
    func testForegroundRestoreUsesNormalPollingAndNoBackgroundLease() async {
        foreground = true
        let owner = FamilyRadioInbox(wake: makeWake(), center: NotificationCenter())
        owner.restored(); await Task.yield()
        XCTAssertEqual(begun, 0); XCTAssertEqual(refreshed, 0)
        owner.stop()
    }
}
