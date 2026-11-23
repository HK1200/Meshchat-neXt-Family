// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

@MainActor private final class DispatcherDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    var reports: [(UUID, String)] = [], endedIDs: [UUID] = []
    var holding = false, failing = false, closed = false
    var pending: [UUID: CheckedContinuation<Void, Error>] = [:]
    func incoming(_ id: UUID, name: String) async throws {
        guard !closed else { throw CancellationError() }
        reports.append((id, name))
        if failing { throw URLError(.cannotConnectToHost) }
        if holding { try await withCheckedThrowingContinuation { pending[id] = $0 } }
    }
    func release() { let values = pending; pending.removeAll(); for value in values.values { value.resume() } }
    func close() { closed = true; let values = pending; pending.removeAll(); for value in values.values { value.resume(throwing: CancellationError()) } }
    func start(_ id: UUID, name: String) async throws { }
    func answer(_ id: UUID) async throws { _ = await events?.systemAnswer(id) }
    func end(_ id: UUID) async throws { _ = await events?.systemEnd(id) }
    func mute(_ id: UUID, muted: Bool) async throws { _ = await events?.systemMute(id, muted: muted) }
    func connected(_ id: UUID) { }
    func ended(_ id: UUID, failed: Bool) { endedIDs.append(id) }
}
@MainActor private final class DispatcherReplay: NextCallWakeReplayStoring {
    var value: Data?
    func read() throws -> Data? { value }
    func write(_ data: Data) throws { value = data }
}
@MainActor private final class DispatcherEngine {
    var calls = 0, holding = false, failing = false, closed = false
    var pending: CheckedContinuation<NextRuntimeSession, Error>?
    func start(_ configuration: Data?) async throws -> NextRuntimeSession {
        calls += 1; XCTAssertNil(configuration)
        if failing || closed { throw URLError(.cannotConnectToHost) }
        if holding { return try await withCheckedThrowingContinuation { pending = $0 } }
        return NextRuntimeSession(url: URL(string: "http://127.0.0.1:44242")!, address: nil)
    }
    func close() { closed = true; let value = pending; pending = nil; value?.resume(throwing: CancellationError()) }
}
@MainActor private final class DispatcherFixture {
    let driver = DispatcherDriver(), engine = DispatcherEngine()
    let system: FamilySystemCalls
    let router: NextReticulumWakeRouter
    let runtime: NextRuntimeStartup
    let payload: Data
    let caller: String
    var context: NextCallWakeContext?
    var dispatcher: NextCallWakeDispatcher!
    init(enabled: Bool = true) throws {
        let file = try XCTUnwrap(Bundle(for: CallWakeDispatcherTests.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        let vectors = try XCTUnwrap(fixture["vectors"] as? [String: Any])
        payload = try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors["valid"]))
        caller = try XCTUnwrap(fixture["caller"] as? String)
        let agreement = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: Data((0..<32).map(UInt8.init)))
        let signing = try Curve25519.Signing.PrivateKey(rawRepresentation: Data((32..<64).map(UInt8.init)))
        context = NextCallWakeContext(recipientPrivateKey: agreement.rawRepresentation,
            recipientPublicKey: agreement.publicKey.rawRepresentation + signing.publicKey.rawRepresentation,
            audience: "private-calls", approvedNames: [caller: "Approved fixture"])
        system = FamilySystemCalls(driver: driver, preferences: nil, enabled: enabled)
        router = NextReticulumWakeRouter(system: system, store: DispatcherReplay(), now: { Date(timeIntervalSince1970: 1000) })
        runtime = NextRuntimeStartup(start: engine.start)
        dispatcher = NextCallWakeDispatcher(system: system, router: router, runtime: runtime, context: { [weak self] in self?.context })
    }
    func close() { dispatcher.stop(); driver.close(); engine.close() }
}

@MainActor final class CallWakeDispatcherTests: XCTestCase {
    private func ready(_ condition: () -> Bool) async throws {
        for _ in 0..<500 { if condition() { return }; try await Task.sleep(for: .milliseconds(5)) }
        XCTFail("The private push-dispatch condition did not finish"); throw URLError(.timedOut)
    }
    private var actions: FamilySystemCallActions {
        FamilySystemCallActions(prepareAudio: { true }, start: { true }, answer: { true }, end: {}, mute: { _ in true })
    }
    func testAcceptedWakeCompletesAfterCallKitWithoutWaitingForPython() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.driver.holding = true; f.engine.holding = true
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { !f.driver.pending.isEmpty && f.engine.pending != nil }
        XCTAssertEqual(completions, 0)
        f.driver.release(); try await ready { completions == 1 }
        XCTAssertNotNil(f.engine.pending); XCTAssertTrue(f.system.hasCall)
        XCTAssertEqual(f.engine.calls, 1)
    }
    func testStartupFailureCannotCompleteThePushBeforeTheRealReportCallback() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.driver.holding = true; f.engine.failing = true
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { !f.driver.pending.isEmpty && f.engine.calls == 1 && !f.system.hasCall }
        XCTAssertEqual(completions, 0)
        f.driver.release(); try await ready { completions == 1 }
        XCTAssertFalse(f.system.hasCall)
    }
    func testCancellationBeforeTheReportTaskRunsStillReportsBeforeCompletion() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.driver.holding = true
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        f.dispatcher.stop()
        try await ready { !f.driver.pending.isEmpty }
        XCTAssertEqual(completions, 0); XCTAssertFalse(f.system.hasCall)
        f.driver.release(); try await ready { completions == 1 }
        XCTAssertEqual(f.driver.reports.count, 1)
    }
    func testTransportAdoptionRetainsItsCallAndTheSameReportAcknowledgement() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.driver.holding = true
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { !f.driver.pending.isEmpty }
        let pending = try XCTUnwrap(f.router.pendingIncoming(peer: f.caller, service: .reticulum))
        let real = FamilySystemCallKey(service: .reticulum, id: "authenticated-private-transport")
        XCTAssertTrue(f.system.attachIncoming(pending, to: real, actions: actions))
        f.router.attached(pending, to: real)
        XCTAssertEqual(completions, 0)
        f.driver.release(); try await ready { completions == 1 }
        XCTAssertTrue(f.system.contains(real)); XCTAssertTrue(f.driver.endedIDs.isEmpty)
        f.system.finish(real)
    }
    func testRequiredUnusablePushReportsFreshGenericCallEvenWhenControlsAreOff() async throws {
        let f = try DispatcherFixture(enabled: false); defer { f.close() }
        f.context = nil; f.driver.holding = true
        var completions = 0
        f.dispatcher.receive(Data("malformed".utf8), mustReport: true) { completions += 1 }
        try await ready { !f.driver.pending.isEmpty }
        XCTAssertEqual(completions, 0); XCTAssertEqual(f.engine.calls, 0)
        XCTAssertEqual(f.driver.reports.first?.1, "Unavailable call")
        f.driver.release(); try await ready { completions == 1 }
        XCTAssertEqual(f.driver.endedIDs.count, 1); XCTAssertFalse(f.system.enabled)
    }
    func testOptionalUnusablePushDoesNotReportOrInitializeAnything() throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.context = nil
        var completions = 0
        f.dispatcher.receive(Data(), mustReport: false) { completions += 1 }
        XCTAssertEqual(completions, 1); XCTAssertTrue(f.driver.reports.isEmpty)
        XCTAssertEqual(f.engine.calls, 0); XCTAssertFalse(f.system.hasCall)
    }
    func testDuplicateRequiredPushCannotEndOrReplaceItsExistingApprovedCall() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { completions == 1 }
        let key = try XCTUnwrap(f.router.pendingIncoming(peer: f.caller, service: .reticulum))
        let original = try XCTUnwrap(f.driver.reports.first?.0)
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { completions == 2 }
        XCTAssertTrue(f.system.contains(key)); XCTAssertEqual(f.driver.reports.count, 2)
        XCTAssertNotEqual(f.driver.reports[1].0, original)
        XCTAssertFalse(f.driver.endedIDs.contains(original)); XCTAssertEqual(f.engine.calls, 1)
    }
    func testRevocationEndsThePendingCallButStillWaitsForReportAcknowledgement() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.driver.holding = true
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { !f.driver.pending.isEmpty }
        f.context = nil; f.dispatcher.refreshConsent()
        XCTAssertFalse(f.system.hasCall); XCTAssertEqual(completions, 0)
        f.driver.release(); try await ready { completions == 1 }
    }
    func testCallKitFailureCompletesOnceWithoutLeavingAnOwnedCall() async throws {
        let f = try DispatcherFixture(); defer { f.close() }
        f.driver.failing = true
        var completions = 0
        f.dispatcher.receive(f.payload, mustReport: true) { completions += 1 }
        try await ready { completions == 1 && !f.system.hasCall }
        XCTAssertEqual(f.driver.reports.count, 1)
    }
}
