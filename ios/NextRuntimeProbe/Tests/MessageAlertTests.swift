import XCTest
import UserNotifications

@MainActor
private final class FakeNextAlerts: NextAlertPosting {
    var status: UNAuthorizationStatus = .authorized
    var lockScreenStatus: UNNotificationSetting = .disabled
    func lockScreen() async -> UNNotificationSetting { lockScreenStatus }
    var requests = 0
    var attempts = 0
    var fail = false
    var posted: [NextUnreadNotice] = []
    func authorization() async -> UNAuthorizationStatus { status }
    func requestAuthorization() async throws -> Bool {
        requests += 1
        status = .authorized
        await Task.yield()
        return true
    }
    func post(_ notice: NextUnreadNotice) async throws {
        attempts += 1
        await Task.yield()
        if fail { throw NSError(domain: "Private test failure", code: 1) }
        posted.append(notice)
    }
}

final class MessageAlertTests: XCTestCase {
    private func notice(_ id: Int, peer: String = String(repeating: "a", count: 32)) -> NextUnreadNotice {
        let hex = String(id, radix: 16)
        return NextUnreadNotice(id: id, hash: String(repeating: "0", count: 64 - hex.count) + hex, peer: peer)
    }

    @MainActor
    func testAuthorizationDoesNotClaimThatLockScreenAlertsAreEnabled() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        await alerts.refreshAuthorization()
        XCTAssertTrue(alerts.enabled)
        XCTAssertEqual(alerts.lockScreenSetting, .disabled)
        XCTAssertEqual(center.requests, 0)
        center.lockScreenStatus = .enabled
        await alerts.refreshAuthorization()
        XCTAssertEqual(alerts.lockScreenSetting, .enabled)
        XCTAssertEqual(center.requests, 0)
    }

    @MainActor
    func testVisibleAndDeniedAppsDoNotPostOrRequestPermissionAutomatically() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        await alerts.publish([notice(1)], appActive: true)
        center.status = .denied
        await alerts.publish([notice(2)], appActive: false)
        XCTAssertTrue(center.posted.isEmpty)
        XCTAssertEqual(center.requests, 0)
    }

    @MainActor
    func testFirstPermissionDoesNotReplayExistingOrDeletedOlderMessages() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        center.status = .notDetermined
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        try await alerts.authorize(existing: [notice(3)])
        await alerts.publish([notice(2), notice(3), notice(4)], appActive: false)
        XCTAssertEqual(center.requests, 1)
        XCTAssertEqual(center.posted, [notice(4)])
        let reopened = NextMessageAlerts(center: center, defaults: defaults)
        await reopened.publish([notice(4), notice(5)], appActive: false)
        XCTAssertEqual(center.posted, [notice(4), notice(5)])
    }

    @MainActor
    func testRefreshDuringPermissionPromptDoesNotAlertBaselineMessages() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        center.status = .notDetermined
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        async let enabling: Void = alerts.authorize(existing: [notice(1)])
        async let refreshing: Void = alerts.publish([notice(1)], appActive: false)
        _ = try await (enabling, refreshing)
        XCTAssertTrue(center.posted.isEmpty)
    }

    @MainActor
    func testOSFailureIsRetriedAndRepeatedRefreshDoesNotDuplicate() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        center.fail = true
        await alerts.publish([notice(1)], appActive: false)
        center.fail = false
        await alerts.publish([notice(1)], appActive: false)
        await alerts.publish([notice(1)], appActive: false)
        XCTAssertEqual(center.attempts, 2)
        XCTAssertEqual(center.posted, [notice(1)])
    }

    @MainActor
    func testConcurrentRefreshesAreCoalesced() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        async let first: Void = alerts.publish([notice(1)], appActive: false)
        async let second: Void = alerts.publish([notice(1)], appActive: false)
        _ = await (first, second)
        XCTAssertEqual(center.posted, [notice(1)])
    }

    @MainActor
    func testOnlyExactMessageAndContactIdentifiersCanOpenAConversation() throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let alerts = NextMessageAlerts(center: FakeNextAlerts(), defaults: defaults)
        alerts.routeMessage(hash: notice(1).hash, peer: "https://example.invalid")
        XCTAssertNil(alerts.requestedAddress)
        alerts.routeMessage(hash: notice(1).hash, peer: notice(1).peer + "\n")
        XCTAssertNil(alerts.requestedAddress)
        alerts.routeMessage(hash: "invalid", peer: notice(1).peer)
        XCTAssertNil(alerts.requestedAddress)
        alerts.routeMessage(hash: notice(1).hash, peer: notice(1).peer)
        XCTAssertEqual(alerts.requestedAddress, notice(1).peer)
        alerts.consumedRoute()
        XCTAssertNil(alerts.requestedAddress)
    }
    @MainActor
    func testMeshCoreAndReticulumPermissionBaselinesStayIndependent() async throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = FakeNextAlerts()
        center.status = .notDetermined
        let alerts = NextMessageAlerts(center: center, defaults: defaults)
        let key = "meshcore-" + String(repeating: "a", count: 64)
        let existing = NextUnreadNotice(id: 900, hash: String(repeating: "b", count: 64),
                                        peer: String(repeating: "c", count: 32), meshcoreKey: key)
        try await alerts.authorize(existing: [notice(1), existing])
        let fresh = NextUnreadNotice(id: 901, hash: String(repeating: "d", count: 64),
                                     peer: existing.peer, meshcoreKey: key)
        await alerts.publish([existing, fresh, notice(2)], appActive: false)
        XCTAssertEqual(center.posted, [fresh, notice(2)])
        await alerts.publish([fresh, notice(2)], appActive: false)
        XCTAssertEqual(center.posted.count, 2)
    }

    @MainActor
    func testMeshCoreNotificationKeysCannotBecomeArbitraryRoutes() throws {
        let suite = "next-alert-test." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let alerts = NextMessageAlerts(center: FakeNextAlerts(), defaults: defaults)
        alerts.routeMessage(hash: notice(1).hash, peer: notice(1).peer, meshcoreKey: "https://example.invalid")
        XCTAssertNil(alerts.requestedMeshCoreKey)
        let key = "meshcore-" + String(repeating: "a", count: 64)
        alerts.routeMessage(hash: notice(1).hash, peer: notice(1).peer, meshcoreKey: key)
        XCTAssertNil(alerts.requestedAddress)
        XCTAssertEqual(alerts.requestedMeshCoreKey, key)
        alerts.consumedRoute()
        XCTAssertNil(alerts.requestedMeshCoreKey)
    }

    func testMeshCoreConversationTargetsAreStrictlyValidated() {
        let owner = String(repeating: "a", count: 64)
        let peer = String(repeating: "b", count: 64)
        let target = NextMeshCoreAlertTarget(owner: owner, target: peer, kind: "direct", radio_id: "default")
        XCTAssertEqual(target.fragment, "/messages?meshcore=" + peer + "&meshcoreRadio=default")
        XCTAssertNil(NextMeshCoreAlertTarget(owner: owner, target: peer + "\n", kind: "direct", radio_id: nil).fragment)
        XCTAssertNil(NextMeshCoreAlertTarget(owner: owner, target: peer, kind: "direct", radio_id: "default&other=1").fragment)
        XCTAssertNil(NextMeshCoreAlertTarget(owner: owner, target: peer, kind: "unknown", radio_id: nil).fragment)
    }

}
