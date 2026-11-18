import Foundation
import XCTest
@testable import FamilyLive

@MainActor
private final class FakeSystemCallDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    var reports: [UUID] = []
    var endedIDs: [UUID] = []
    var connectedIDs: [UUID] = []
    var pauseReport = false
    var failReport = false
    var reportGate: CheckedContinuation<Void, Error>?
    func incoming(_ id: UUID, name: String) async throws {
        reports.append(id)
        if pauseReport { try await withCheckedThrowingContinuation { reportGate = $0 } }
        if failReport { throw NSError(domain: "Private CallKit fixture", code: 1) }
    }
    func start(_ id: UUID, name: String) async throws { try await incoming(id, name: name) }
    func answer(_ id: UUID) async throws { _ = await events?.systemAnswer(id) }
    func end(_ id: UUID) async throws { _ = await events?.systemEnd(id) }
    func mute(_ id: UUID, muted: Bool) async throws { _ = await events?.systemMute(id, muted: muted) }
    func connected(_ id: UUID) { connectedIDs.append(id) }
    func ended(_ id: UUID, failed: Bool) { endedIDs.append(id) }
}

final class FamilySystemCallTests: XCTestCase {
    @MainActor
    private func settle(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        let deadline = ContinuousClock.now.advanced(by: .seconds(1))
        while !predicate() && ContinuousClock.now < deadline { try? await Task.sleep(for: .milliseconds(1)) }
        XCTAssertTrue(predicate(), file: file, line: line)
    }

    @MainActor
    private func actions(prepare: @escaping () async -> Bool = { true },
                         start: @escaping () async -> Bool = { true },
                         answer: @escaping () async -> Bool = { true },
                         end: @escaping () async -> Void = {},
                         mute: @escaping (Bool) async -> Bool = { _ in true }) -> FamilySystemCallActions {
        FamilySystemCallActions(prepareAudio: prepare, start: start, answer: answer, end: end, mute: mute)
    }

    @MainActor
    func testOutgoingWaitsForSystemAudioAndConnectsOnlyOnce() async {
        let driver = FakeSystemCallDriver()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let key = FamilySystemCallKey(service: .sip, id: "outgoing-1")
        var started = 0
        XCTAssertTrue(calls.track(key, name: "Approved test", incoming: false,
            actions: actions(start: { started += 1; return true })))
        await settle { driver.reports.count == 1 }
        let id = driver.reports[0]
        let accepted = await calls.systemStart(id)
        XCTAssertTrue(accepted)
        XCTAssertEqual(started, 0)
        calls.update(key, connected: true)
        XCTAssertTrue(driver.connectedIDs.isEmpty)
        calls.systemAudioActivated()
        await settle { started == 1 && driver.connectedIDs.count == 1 }
        calls.systemAudioActivated()
        calls.update(key, connected: true)
        XCTAssertEqual(driver.connectedIDs, [id])
        calls.systemAudioDeactivated()
        XCTAssertFalse(calls.allowsAudio(key))
        XCTAssertTrue(calls.contains(key))
    }

    @MainActor
    func testIncomingAnswerWaitsForActivationAndEndsThroughSystemControls() async {
        let driver = FakeSystemCallDriver()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let key = FamilySystemCallKey(service: .reticulum, id: "incoming-1")
        var answered = 0
        var ended = 0
        var muted: [Bool] = []
        _ = calls.track(key, name: "Approved test", incoming: true, actions: actions(
            answer: { answered += 1; return true }, end: { ended += 1 }, mute: { muted.append($0); return true }))
        await settle { driver.reports.count == 1 }
        let id = driver.reports[0]
        let accepted = await calls.systemAnswer(id)
        XCTAssertTrue(accepted)
        let duplicate = await calls.systemAnswer(id)
        XCTAssertFalse(duplicate)
        XCTAssertEqual(answered, 0)
        calls.systemAudioActivated()
        await settle { answered == 1 }
        let answeredAgain = await calls.systemAnswer(id)
        XCTAssertFalse(answeredAgain)
        let didMute = await calls.systemMute(id, muted: true)
        XCTAssertTrue(didMute)
        XCTAssertEqual(muted, [true])
        let didEnd = await calls.systemEnd(id)
        XCTAssertTrue(didEnd)
        XCTAssertEqual(ended, 1)
        XCTAssertFalse(calls.hasCall)
        XCTAssertFalse(calls.audioReady)
    }

    @MainActor
    func testOldActionsCannotAffectReplacementCallsOnEitherTransport() async {
        for service in [FamilySystemCallKey.Service.reticulum, .sip] {
            let driver = FakeSystemCallDriver()
            let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
            let old = FamilySystemCallKey(service: service, id: "old")
            let new = FamilySystemCallKey(service: service, id: "new")
            _ = calls.track(old, name: "Old approved", incoming: true, actions: actions())
            await settle { driver.reports.count == 1 }
            let oldID = driver.reports[0]
            calls.finish(old)
            var ended = 0
            var muted = 0
            _ = calls.track(new, name: "New approved", incoming: true,
                actions: actions(end: { ended += 1 }, mute: { _ in muted += 1; return true }))
            await settle { driver.reports.count == 2 }
            let oldEnd = await calls.systemEnd(oldID)
            let oldMute = await calls.systemMute(oldID, muted: true)
            let oldAnswer = await calls.systemAnswer(oldID)
            XCTAssertFalse(oldEnd || oldMute || oldAnswer)
            calls.systemActionTimedOut(oldID)
            XCTAssertTrue(calls.contains(new))
            XCTAssertEqual(ended, 0)
            XCTAssertEqual(muted, 0)
        }
    }

    @MainActor
    func testPermissionResultForEndedCallCannotAnswerReplacement() async {
        let driver = FakeSystemCallDriver()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let old = FamilySystemCallKey(service: .reticulum, id: "old")
        let new = FamilySystemCallKey(service: .reticulum, id: "new")
        var gate: CheckedContinuation<Bool, Never>?
        var answered = 0
        _ = calls.track(old, name: "Approved old", incoming: true, actions: actions(
            prepare: { await withCheckedContinuation { gate = $0 } }, answer: { answered += 1; return true }))
        await settle { driver.reports.count == 1 }
        let oldID = driver.reports[0]
        let answerTask = Task { await calls.systemAnswer(oldID) }
        await settle { gate != nil }
        calls.finish(old)
        _ = calls.track(new, name: "Approved new", incoming: true, actions: actions())
        gate?.resume(returning: true)
        let accepted = await answerTask.value
        XCTAssertFalse(accepted)
        XCTAssertTrue(calls.contains(new))
        XCTAssertEqual(answered, 0)
    }

    @MainActor
    func testLateReportCompletionCleansUpOnlyItsOwnCall() async {
        let driver = FakeSystemCallDriver()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let old = FamilySystemCallKey(service: .sip, id: "old")
        let new = FamilySystemCallKey(service: .sip, id: "new")
        driver.pauseReport = true
        _ = calls.track(old, name: "Old", incoming: true, actions: actions())
        await settle { driver.reportGate != nil }
        let oldID = driver.reports[0]
        let gate = driver.reportGate
        calls.finish(old)
        driver.pauseReport = false
        _ = calls.track(new, name: "New", incoming: true, actions: actions())
        await settle { driver.reports.count == 2 }
        gate?.resume()
        await settle { driver.endedIDs.count == 2 }
        XCTAssertEqual(driver.endedIDs, [oldID, oldID])
        XCTAssertTrue(calls.contains(new))
    }

    @MainActor
    func testDeniedAudioPreparationAndProviderFailureEndTheirOwnCalls() async {
        let driver = FakeSystemCallDriver()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let key = FamilySystemCallKey(service: .sip, id: "denied")
        var ended = 0
        _ = calls.track(key, name: "Approved", incoming: true, actions: actions(prepare: { false }, end: { ended += 1 }))
        await settle { driver.reports.count == 1 }
        let accepted = await calls.systemAnswer(driver.reports[0])
        XCTAssertFalse(accepted)
        XCTAssertEqual(ended, 1)
        XCTAssertFalse(calls.hasCall)
        driver.failReport = true
        let next = FamilySystemCallKey(service: .sip, id: "report-failure")
        _ = calls.track(next, name: "Approved", incoming: true, actions: actions(end: { ended += 1 }))
        await settle { ended == 2 }
        XCTAssertFalse(calls.hasCall)
    }

    @MainActor
    func testResetAndGuardianToggleCannotLeaveAnActiveGhostCall() async {
        let driver = FakeSystemCallDriver()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        let key = FamilySystemCallKey(service: .reticulum, id: "reset")
        var ended = 0
        _ = calls.track(key, name: "Approved", incoming: true, actions: actions(end: { ended += 1 }))
        XCTAssertFalse(calls.setEnabled(false))
        calls.systemReset()
        await settle { ended == 1 }
        XCTAssertFalse(calls.hasCall)
        XCTAssertTrue(calls.setEnabled(false))
        XCTAssertTrue(calls.track(key, name: "Approved", incoming: true, actions: actions()))
        XCTAssertFalse(calls.hasCall)
        XCTAssertTrue(calls.allowsAudio(key))
    }
}
