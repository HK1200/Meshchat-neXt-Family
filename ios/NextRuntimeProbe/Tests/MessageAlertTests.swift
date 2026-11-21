import XCTest
import UserNotifications

@MainActor
private final class FakeNextAlerts: NextAlertPosting {
    var status: UNAuthorizationStatus = .authorized
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
}
