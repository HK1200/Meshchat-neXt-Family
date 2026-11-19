import XCTest
@testable import FamilyLive

@MainActor
private final class RadioWakeHarness {
    var time: TimeInterval = 0
    var foreground = false
    var nextID = 0
    var ends: [Int] = []
    var expirations: [Int: FamilyRadioWake.Expiration] = [:]
    var prepared = 0
    var refreshed = 0
    var allowed = true
    var expireImmediately = false
    var onRefresh: (() async -> Void)?
    var onPrepare: (() async -> Void)?
    var onPause: (() -> Void)?

    func make() -> FamilyRadioWake {
        FamilyRadioWake(begin: { expired in
            guard self.allowed else { return nil }
            self.nextID += 1
            self.expirations[self.nextID] = expired
            if self.expireImmediately { expired() }
            return self.nextID
        }, end: { self.ends.append($0) }, now: { self.time }, active: { self.foreground },
        prepare: { self.prepared += 1; await self.onPrepare?() },
        refresh: { self.refreshed += 1; await self.onRefresh?() },
        pause: { self.time += 1; self.onPause?(); await Task.yield() })
    }
}

final class FamilyRadioWakeTests: XCTestCase {
    @MainActor
    private func settle(_ predicate: () -> Bool) async {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while !predicate() && ContinuousClock.now < deadline { try? await Task.sleep(for: .milliseconds(1)) }
        XCTAssertTrue(predicate())
    }

    @MainActor
    func testForegroundPacketsUseNormalPollingWithoutTakingBackgroundTime() {
        let h = RadioWakeHarness(); h.foreground = true
        let wake = h.make(); wake.received()
        XCTAssertFalse(wake.isRunning)
        XCTAssertEqual(h.nextID, 0)
        XCTAssertEqual(h.refreshed, 0)
    }

    @MainActor
    func testBurstPacketsShareOneLeaseAndLeaveTimeForParserCompletion() async {
        let h = RadioWakeHarness(); let wake = h.make()
        wake.received(); wake.received(); wake.received()
        await settle { !wake.isRunning }
        XCTAssertEqual(h.nextID, 1)
        XCTAssertEqual(h.prepared, 1)
        XCTAssertEqual(h.ends, [1])
        XCTAssertGreaterThanOrEqual(h.time, 3)
        XCTAssertGreaterThanOrEqual(h.refreshed, 4)
    }

    @MainActor
    func testContinuousPacketsCannotExtendWorkPastFifteenSeconds() async {
        let h = RadioWakeHarness(); let wake = h.make()
        h.onRefresh = { wake.received() }
        wake.received()
        await settle { !wake.isRunning }
        XCTAssertEqual(h.time, 15)
        XCTAssertEqual(h.nextID, 1)
        XCTAssertEqual(h.ends, [1])
        XCTAssertEqual(h.refreshed, 15)
        h.onRefresh = nil
    }

    @MainActor
    func testDeniedAndImmediatelyExpiredLeasesNeverStartInboxWork() async {
        for immediate in [false, true] {
            let h = RadioWakeHarness(); h.allowed = immediate; h.expireImmediately = immediate
            let wake = h.make(); wake.received()
            await Task.yield()
            XCTAssertFalse(wake.isRunning)
            XCTAssertEqual(h.refreshed, 0)
            XCTAssertEqual(h.ends, immediate ? [1] : [])
        }
    }

    @MainActor
    func testExpirationCancelsPendingPreparationAndOldCallbackCannotEndReplacement() async {
        let h = RadioWakeHarness(); let wake = h.make()
        var gate: CheckedContinuation<Void, Never>?
        h.onPrepare = { await withCheckedContinuation { gate = $0 } }
        wake.received()
        await settle { gate != nil }
        h.expirations[1]?()
        XCTAssertFalse(wake.isRunning)
        XCTAssertEqual(h.ends, [1])
        h.onPrepare = nil
        wake.received()
        h.expirations[1]?()
        XCTAssertTrue(wake.isRunning)
        gate?.resume(); gate = nil
        await settle { !wake.isRunning }
        XCTAssertEqual(h.ends, [1, 2])
        XCTAssertEqual(h.nextID, 2)
        XCTAssertEqual(h.refreshed, 4)
    }

    @MainActor
    func testExpiredRuntimeReadCannotQueueOverlappingReadsOnNextWake() async {
        let h = RadioWakeHarness(); let wake = h.make()
        var gate: CheckedContinuation<Void, Never>?
        var finishedRead = false
        h.onRefresh = { await withCheckedContinuation { gate = $0 }; finishedRead = true }
        wake.received()
        await settle { gate != nil }
        h.expirations[1]?()
        wake.received()
        await settle { !wake.isRunning }
        XCTAssertEqual(h.refreshed, 1)
        XCTAssertEqual(h.ends, [1, 2])
        h.onRefresh = nil
        gate?.resume(); gate = nil
        // Allow the cancelled read to release the in-flight guard.
        await settle { finishedRead }
        wake.received()
        await settle { !wake.isRunning }
        XCTAssertGreaterThan(h.refreshed, 1)
        XCTAssertEqual(h.ends, [1, 2, 3])
    }

    @MainActor
    func testOwnDeadlineReleasesLeaseDuringSuspendedPermissionRequest() async {
        var gate: CheckedContinuation<Void, Never>?
        var ended: [Int] = []
        var refreshed = 0
        let wake = FamilyRadioWake(begin: { _ in 1 }, end: { ended.append($0) },
            now: { 0 }, active: { false },
            prepare: { await withCheckedContinuation { gate = $0 } },
            refresh: { refreshed += 1 }, pause: { await Task.yield() },
            timeout: { while gate == nil { await Task.yield() } })
        wake.received()
        await settle { gate != nil && !wake.isRunning }
        XCTAssertEqual(ended, [1])
        XCTAssertEqual(refreshed, 0)
        gate?.resume(); gate = nil
        await Task.yield()
        XCTAssertEqual(ended, [1])
    }

    @MainActor
    func testForegroundTransitionReleasesLeaseAndStopsExtraPolling() async {
        let h = RadioWakeHarness(); let wake = h.make()
        h.onPause = { h.foreground = true; wake.stop() }
        wake.received()
        await settle { !wake.isRunning }
        XCTAssertEqual(h.ends, [1])
        XCTAssertEqual(h.refreshed, 1)
        h.onPause = nil
    }
}
