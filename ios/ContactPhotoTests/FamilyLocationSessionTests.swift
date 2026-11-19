import XCTest
@testable import FamilyLive

@MainActor
private final class LocationSessionHarness {
    var time: TimeInterval = 1_000
    var starts = 0
    var stops = 0
    lazy var session = FamilyLocationSession(now: { [weak self] in self?.time ?? 0 },
        start: { [weak self] in self?.starts += 1 }, stop: { [weak self] in self?.stops += 1 })
    func update(active: Bool = true, allowed: Bool = true, foreground: Bool = true,
                background: Bool = false, supported: Bool = true, until: TimeInterval? = 1_100) {
        session.update(active: active, authorized: allowed, foreground: foreground,
                       background: background, supported: supported, until: until)
    }
}

final class FamilyLocationSessionTests: XCTestCase {
    @MainActor
    func testSavingBackgroundPreferenceWithoutActiveSharingNeverStartsLocation() {
        let h = LocationSessionHarness()
        h.update(active: false, background: true)
        XCTAssertEqual(h.session.mode, .off)
        XCTAssertEqual(h.starts, 0)
        XCTAssertFalse(h.session.canSubmit)
    }

    @MainActor
    func testDefaultOffKeepsForegroundSamplingAndStopsAtLock() {
        let h = LocationSessionHarness()
        h.update()
        XCTAssertEqual(h.session.mode, .foreground)
        XCTAssertTrue(h.session.canSubmit)
        XCTAssertEqual(h.starts, 0)
        h.update(foreground: false)
        XCTAssertEqual(h.session.mode, .off)
        XCTAssertFalse(h.session.canSubmit)
    }

    @MainActor
    func testExplicitForegroundStartCanContinueWithWhenInUseAccessWhileLocked() {
        let h = LocationSessionHarness()
        h.update(background: true)
        XCTAssertEqual(h.starts, 1)
        h.update(foreground: false, background: true)
        XCTAssertEqual(h.session.mode, .continuous)
        XCTAssertTrue(h.session.canSubmit)
        XCTAssertEqual(h.starts, 1)
        XCTAssertEqual(h.stops, 0)
        h.update(background: true)
        XCTAssertEqual(h.starts, 1)
    }

    @MainActor
    func testColdBackgroundLaunchCannotStartASavedSharingSession() {
        let h = LocationSessionHarness()
        h.update(foreground: false, background: true)
        XCTAssertEqual(h.session.mode, .off)
        XCTAssertEqual(h.starts, 0)
        h.update(background: true)
        XCTAssertEqual(h.starts, 1)
    }

    @MainActor
    func testExpiryRejectsFixesAndStopsContinuousLocationOnlyOnce() {
        let h = LocationSessionHarness()
        h.update(background: true, until: 1_010)
        let oldGeneration = h.session.generation
        h.time = 1_010
        XCTAssertFalse(h.session.canSubmit)
        h.session.expireIfNeeded()
        h.session.expireIfNeeded()
        XCTAssertEqual(h.session.mode, .off)
        XCTAssertEqual(h.stops, 1)
        XCTAssertNotEqual(h.session.generation, oldGeneration)
    }

    @MainActor
    func testOngoingSharingContinuesUntilExplicitStop() {
        let h = LocationSessionHarness()
        h.update(background: true, until: -1)
        h.time = 10_000_000
        h.session.expireIfNeeded()
        XCTAssertTrue(h.session.canSubmit)
        h.session.stop()
        XCTAssertFalse(h.session.canSubmit)
        XCTAssertEqual(h.stops, 1)
    }

    @MainActor
    func testTurningBackgroundOffWhileLockedInvalidatesPendingCallbacks() {
        let h = LocationSessionHarness()
        h.update(background: true)
        let oldGeneration = h.session.generation
        h.update(foreground: false, background: false)
        XCTAssertEqual(h.stops, 1)
        XCTAssertFalse(h.session.canSubmit)
        XCTAssertNotEqual(h.session.generation, oldGeneration)
    }

    @MainActor
    func testPermissionRevocationStopsAndDoesNotRestartInBackground() {
        let h = LocationSessionHarness()
        h.update(background: true)
        h.update(allowed: false, foreground: false, background: true)
        XCTAssertFalse(h.session.canSubmit)
        XCTAssertEqual(h.stops, 1)
        h.update(foreground: false, background: true)
        XCTAssertEqual(h.starts, 1)
        XCTAssertEqual(h.session.mode, .off)
    }

    @MainActor
    func testMissingBackgroundCapabilityNeverStartsTheUnsupportedService() {
        let h = LocationSessionHarness()
        h.update(background: true, supported: false)
        XCTAssertEqual(h.session.mode, .foreground)
        XCTAssertEqual(h.starts, 0)
        h.update(foreground: false, background: true, supported: false)
        XCTAssertFalse(h.session.canSubmit)
    }

    @MainActor
    func testMissingExpiredAndNonfiniteDeadlinesCannotEnableLocation() {
        let h = LocationSessionHarness()
        let deadlines: [TimeInterval?] = [nil, 0, 999, Double.infinity, Double.nan]
        for until in deadlines {
            h.update(background: true, until: until)
            XCTAssertFalse(h.session.canSubmit)
            XCTAssertEqual(h.session.mode, .off)
        }
        XCTAssertEqual(h.starts, 0)
    }
}
