import Foundation
import XCTest

@MainActor
final class NextLocationTests: XCTestCase {
    private func raw(_ changes: [String: Any] = [:]) -> [String: Any] {
        var value: [String: Any] = ["op": "start", "session": String(repeating: "a", count: 32),
            "active": true, "background": false, "until": 1800.0,
            "revisions": [String(repeating: "b", count: 32)]]
        value.merge(changes) { _, new in new }; return value
    }
    func testNativeRevocationSurvivesBackendRestart() throws {
        let suite = "NextLocationTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let first = NextLocationGrants(defaults: defaults)
        let revision = String(repeating: "b", count: 32)
        XCTAssertFalse(first.permitsResume([revision]))
        first.replace(with: [revision])
        XCTAssertTrue(NextLocationGrants(defaults: defaults).permitsResume([revision]))
        first.revoke()
        XCTAssertFalse(NextLocationGrants(defaults: defaults).permitsResume([revision]))
        XCTAssertFalse(first.permitsResume([]))
        let other = String(repeating: "c", count: 32)
        first.replace(with: [revision, other])
        first.replace(with: [other])
        XCTAssertTrue(first.permitsResume([other]))
        XCTAssertFalse(NextLocationGrants(defaults: defaults).permitsResume([revision, other]))
    }
    func testCommandPreservesExplicitExpiryAndBackgroundChoice() throws {
        let value = try NextLocationCommand(raw(), now: 1000)
        XCTAssertEqual(value.operation, .start); XCTAssertEqual(value.until, 1800)
        XCTAssertFalse(value.background); XCTAssertEqual(value.revisions.count, 1)
    }
    func testMalformedConsentIsRejectedWithoutLocationAccess() {
        let changes: [[String: Any]] = [["active": 1], ["background": 0], ["until": true],
            ["until": 999], ["until": 4606], ["until": Double.nan], ["op": "broadcast"],
            ["session": "not-an-id"], ["revisions": []], ["extra": "not-allowed"],
            ["revisions": [String(repeating: "b", count: 32), String(repeating: "b", count: 32)]]]
        for change in changes {
            XCTAssertThrowsError(try NextLocationCommand(raw(change), now: 1000))
        }
    }
    func testStopAndStatusCanBeIdleButStartCannot() throws {
        let idle: [String: Any] = ["active": false, "until": 0, "revisions": [String]()]
        var stop = idle; stop["op"] = "stop"
        XCTAssertEqual(try NextLocationCommand(raw(stop), now: 1000).operation, .stop)
        XCTAssertThrowsError(try NextLocationCommand(raw(idle), now: 1000))
    }
    func testLockedSharingCannotStartFromAColdBackgroundWake() {
        var started = 0; var stopped = 0
        let session = FamilyLocationSession(now: { 1000 }, start: { started += 1 }, stop: { stopped += 1 })
        session.update(active: true, authorized: true, foreground: false, background: true, supported: true, until: 1800)
        XCTAssertEqual(session.mode, .off); XCTAssertEqual(started, 0); XCTAssertFalse(session.canSubmit)
        session.update(active: true, authorized: true, foreground: true, background: true, supported: true, until: 1800)
        XCTAssertEqual(session.mode, .continuous); XCTAssertEqual(started, 1)
        session.update(active: true, authorized: true, foreground: false, background: true, supported: true, until: 1800)
        XCTAssertTrue(session.canSubmit)
        session.stop(); XCTAssertFalse(session.canSubmit); XCTAssertEqual(stopped, 1)
    }
    func testForegroundOnlySessionStopsOnLockAndExpiryStopsContinuousSampling() {
        var now = 1000.0; var stops = 0
        let session = FamilyLocationSession(now: { now }, start: {}, stop: { stops += 1 })
        session.update(active: true, authorized: true, foreground: true, background: false, supported: true, until: 1800)
        XCTAssertEqual(session.mode, .foreground)
        session.update(active: true, authorized: true, foreground: false, background: false, supported: true, until: 1800)
        XCTAssertFalse(session.canSubmit)
        session.update(active: true, authorized: true, foreground: true, background: true, supported: true, until: 1800)
        now = 1801; session.expireIfNeeded()
        XCTAssertFalse(session.canSubmit); XCTAssertEqual(stops, 1)
    }
}
