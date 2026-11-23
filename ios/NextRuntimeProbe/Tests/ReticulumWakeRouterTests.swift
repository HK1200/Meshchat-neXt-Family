// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

@MainActor
private final class WakeReplayFixture: NextCallWakeReplayStoring {
    enum Failed: Error { case storage }
    var value: Data?
    var failRead = false, failWrite = false
    var writes = 0
    func read() throws -> Data? { if failRead { throw Failed.storage }; return value }
    func write(_ data: Data) throws { if failWrite { throw Failed.storage }; writes += 1; value = data }
}

@MainActor
private final class WakeRouterDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    var incomingIDs: [UUID] = [], endedIDs: [UUID] = []
    func incoming(_ id: UUID, name: String) async throws { incomingIDs.append(id) }
    func start(_ id: UUID, name: String) async throws { incomingIDs.append(id) }
    func answer(_ id: UUID) async throws { _ = await events?.systemAnswer(id) }
    func end(_ id: UUID) async throws { _ = await events?.systemEnd(id) }
    func mute(_ id: UUID, muted: Bool) async throws { _ = await events?.systemMute(id, muted: muted) }
    func connected(_ id: UUID) { }
    func ended(_ id: UUID, failed: Bool) { endedIDs.append(id) }
}

@MainActor
private final class WakeRouterClock {
    var time: TimeInterval = 1000
    var waits: [CheckedContinuation<Void, Error>] = []
    var date: Date { Date(timeIntervalSince1970: time) }
    func delay(_ seconds: TimeInterval) async throws {
        try Task.checkCancellation()
        XCTAssertGreaterThan(seconds, 0); XCTAssertLessThanOrEqual(seconds, 30)
        try await withCheckedThrowingContinuation { waits.append($0) }
    }
    func release() {
        let values = waits; waits.removeAll()
        for value in values { value.resume() }
    }
}

@MainActor
final class ReticulumWakeRouterTests: XCTestCase {
    private func fixture() throws -> [String: Any] {
        let file = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
    }
    private func payload(_ name: String = "valid") throws -> Data {
        let vectors = try XCTUnwrap(fixture()["vectors"] as? [String: Any])
        return try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors[name]))
    }
    private func publicKey() throws -> Data {
        let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: Data((0..<32).map(UInt8.init)))
        let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: Data((32..<64).map(UInt8.init)))
        return agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation
    }
    private func offer(_ router: NextReticulumWakeRouter, name: String = "valid", audience: String = "private-calls",
                       approved: Bool = true, permitted: @escaping @MainActor () -> Bool = { true }) throws -> NextReticulumWakeRouter.Decision {
        let caller = try XCTUnwrap(fixture()["caller"] as? String)
        return router.accept(try payload(name), recipientPrivateKey: Data((0..<32).map(UInt8.init)), recipientPublicKey: try publicKey(),
            audience: audience, approvedNames: approved ? [caller: "Approved fixture"] : [:], permitted: permitted)
    }
    private func ready(_ condition: () -> Bool) async throws {
        for _ in 0..<500 { if condition() { return }; try await Task.sleep(for: .milliseconds(2)) }
        XCTFail("The private wake router did not settle"); throw URLError(.timedOut)
    }
    private var actions: FamilySystemCallActions {
        FamilySystemCallActions(prepareAudio: { true }, start: { false }, answer: { true }, end: {}, mute: { _ in true })
    }
    func testSignedWakeSelectsOnlyItsAuthenticatedVoiceAndKeepsTheSameCallID() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { router.close(); clock.release() }
        guard case .accepted(let id) = try offer(router) else { return XCTFail("Expected the signed fixture") }
        try await ready { driver.incomingIDs == [id] && !clock.waits.isEmpty }
        let caller = try XCTUnwrap(fixture()["caller"] as? String)
        XCTAssertNil(router.pendingIncoming(peer: String(repeating: "a1", count: 16), service: .reticulum))
        XCTAssertNil(router.pendingIncoming(peer: caller, service: .sip))
        let pending = try XCTUnwrap(router.pendingIncoming(peer: caller, service: .reticulum))
        let actual = FamilySystemCallKey(service: .reticulum, id: "authenticated-fixture-transport")
        XCTAssertTrue(system.attachIncoming(pending, to: actual, actions: actions))
        router.attached(pending, to: actual)
        clock.release(); await Task.yield()
        XCTAssertTrue(system.contains(actual)); XCTAssertEqual(driver.incomingIDs, [id])
        XCTAssertEqual(store.writes, 1)
        system.finish(actual)
    }
    func testReplayJournalSurvivesRouterRecreationWithoutRingingAgain() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let first = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        guard case .accepted(let id) = try offer(first) else { return XCTFail("Expected initial admission") }
        try await ready { driver.incomingIDs == [id] }
        first.close(); clock.release()
        let second = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { second.close(); clock.release() }
        XCTAssertEqual(try offer(second), .duplicate(id))
        XCTAssertFalse(system.hasCall); XCTAssertEqual(store.writes, 1); XCTAssertEqual(driver.incomingIDs, [id])
    }
    func testExpiredFutureForgedCancelledUnapprovedAndWrongAudienceCannotReserveACall() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { router.close(); clock.release() }
        for vector in ["expired", "future", "forged", "cancel"] { XCTAssertEqual(try offer(router, name: vector), .denied) }
        XCTAssertEqual(try offer(router, audience: "wrong-provider"), .denied)
        XCTAssertEqual(try offer(router, approved: false), .denied)
        XCTAssertEqual(try offer(router, permitted: { false }), .denied)
        XCTAssertFalse(system.hasCall); XCTAssertTrue(driver.incomingIDs.isEmpty); XCTAssertEqual(store.writes, 0)
    }
    func testPermissionRevocationReleasesWaitingAnswerAndBlocksLateTransport() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        var permitted = true
        defer { router.close(); clock.release() }
        guard case .accepted(let id) = try offer(router, permitted: { permitted }) else { return XCTFail("Expected admission") }
        let answering = Task { await system.systemAnswer(id) }
        try await Task.sleep(for: .milliseconds(30))
        permitted = false; router.refresh()
        let accepted = await answering.value
        XCTAssertFalse(accepted); XCTAssertFalse(system.hasCall)
        let caller = try XCTUnwrap(fixture()["caller"] as? String)
        XCTAssertNil(router.pendingIncoming(peer: caller, service: .reticulum))
    }
    func testDeadlineExpiresEvenWithoutAnotherIncomingCallback() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { router.close(); clock.release() }
        guard case .accepted(let id) = try offer(router) else { return XCTFail("Expected admission") }
        try await ready { !clock.waits.isEmpty }
        clock.release()
        try await ready { !system.hasCall }
        XCTAssertTrue(driver.endedIDs.contains(id))
    }
    func testBusyCallDoesNotConsumeTheSignedWakeAndCannotBeReplaced() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { router.close(); clock.release() }
        let other = FamilySystemCallKey(service: .sip, id: "existing-private-call")
        XCTAssertTrue(system.track(other, name: "Existing call", incoming: true, actions: actions))
        XCTAssertEqual(try offer(router), .busy); XCTAssertTrue(system.contains(other)); XCTAssertEqual(store.writes, 0)
        system.finish(other)
        guard case .accepted = try offer(router) else { return XCTFail("A busy rejection must not consume the wake") }
    }
    func testUnreadableUnwritableOrCorruptReplayStorageFailsClosed() throws {
        for failure in 0..<3 {
            let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
            store.failRead = failure == 0; store.failWrite = failure == 1
            if failure == 2 { store.value = Data("not a replay journal".utf8) }
            let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
            let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
            defer { router.close(); clock.release() }
            XCTAssertEqual(try offer(router), .unavailable); XCTAssertFalse(system.hasCall)
            XCTAssertTrue(driver.incomingIDs.isEmpty)
        }
    }
    func testWallClockChangesCannotExtendTheSignedPendingCall() async throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { router.close(); clock.release() }
        guard case .accepted = try offer(router) else { return XCTFail("Expected admission") }
        clock.time = 980; router.refresh()
        XCTAssertFalse(system.hasCall)
        clock.time = 1000
        guard case .duplicate = try offer(router) else { return XCTFail("Clock changes must not erase replay protection") }
    }
    func testFullReplayJournalIsPreservedInsteadOfEvictingAnUnexpiredCall() throws {
        let driver = WakeRouterDriver(), store = WakeReplayFixture(), clock = WakeRouterClock()
        let recipient = try XCTUnwrap(fixture()["recipient"] as? String)
        var records: [String: Double] = [:]
        for index in 4..<260 { records[recipient + "/" + String(format: "%032x", UInt32(index))] = 1120 }
        let original = try JSONSerialization.data(withJSONObject: ["version": 1, "records": records], options: [.sortedKeys])
        store.value = original
        let system = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let router = NextReticulumWakeRouter(system: system, store: store, now: { clock.date }, delay: clock.delay)
        defer { router.close(); clock.release() }
        XCTAssertEqual(try offer(router), .unavailable)
        XCTAssertEqual(store.value, original); XCTAssertEqual(store.writes, 0)
        XCTAssertFalse(system.hasCall); XCTAssertTrue(driver.incomingIDs.isEmpty)
    }

}
