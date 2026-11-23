// SPDX-License-Identifier: 0BSD
import Foundation
import XCTest

@MainActor
private final class WakeHandoffDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    var reports: [UUID] = []
    var endedIDs: [UUID] = []
    var pauseReport = false
    var failReport = false
    var reportGate: CheckedContinuation<Void, Never>?
    func incoming(_ id: UUID, name: String) async throws {
        reports.append(id)
        if pauseReport { await withCheckedContinuation { reportGate = $0 } }
        if failReport { throw URLError(.cannotConnectToHost) }
    }
    func start(_ id: UUID, name: String) async throws { reports.append(id) }
    func answer(_ id: UUID) async throws { _ = await events?.systemAnswer(id) }
    func end(_ id: UUID) async throws { _ = await events?.systemEnd(id) }
    func mute(_ id: UUID, muted: Bool) async throws { _ = await events?.systemMute(id, muted: muted) }
    func connected(_ id: UUID) { }
    func ended(_ id: UUID, failed: Bool) { endedIDs.append(id) }
}

@MainActor
final class CallWakeHandoffTests: XCTestCase {
    private let pending = FamilySystemCallKey(service: .reticulum, id: "private-wake-pending")
    private let arrived = FamilySystemCallKey(service: .reticulum, id: "private-authenticated-call")
    private func actions(prepare: @escaping () async -> Bool = { true },
                         answer: @escaping () async -> Bool = { true },
                         end: @escaping () async -> Void = {}) -> FamilySystemCallActions {
        FamilySystemCallActions(prepareAudio: prepare, start: { false }, answer: answer, end: end, mute: { _ in true })
    }
    private func ready(_ condition: () -> Bool) async throws {
        for _ in 0..<500 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(2))
        }
        XCTFail("The private handoff condition did not complete")
        throw URLError(.timedOut)
    }
    func testReservedWakeAdoptsOneTransportWithoutReportingASecondIncomingCall() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        try await ready { driver.reports == [id] }
        XCTAssertTrue(calls.attachIncoming(pending, to: arrived, actions: actions()))
        XCTAssertFalse(calls.contains(pending)); XCTAssertTrue(calls.contains(arrived))
        calls.finish(pending)
        XCTAssertTrue(calls.contains(arrived)); XCTAssertTrue(driver.endedIDs.isEmpty)
        calls.finish(arrived)
        XCTAssertEqual(driver.reports, [id]); XCTAssertEqual(driver.endedIDs, [id])
    }
    func testEarlyAnswerWaitsForTheAuthenticatedTransportAndUsesItsAudioActions() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        var placeholderPreparations = 0, preparations = 0, answers = 0
        var completed: Bool?
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller",
            actions: actions(prepare: { placeholderPreparations += 1; return true })))
        defer { calls.finish(arrived); calls.finish(pending) }
        let task = Task { let value = await calls.systemAnswer(id); completed = value; return value }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNil(completed); XCTAssertEqual(placeholderPreparations, 0)
        calls.systemAudioActivated()
        XCTAssertTrue(calls.attachIncoming(pending, to: arrived,
            actions: actions(prepare: { preparations += 1; return true }, answer: { answers += 1; return true })))
        let accepted = await task.value
        XCTAssertTrue(accepted)
        try await ready { answers == 1 }
        XCTAssertEqual(preparations, 1); XCTAssertEqual(placeholderPreparations, 0)
        XCTAssertEqual(driver.reports, [id])
    }
    func testFinishingPendingWakeRejectsItsWaitingAnswerAndLateTransport() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        let answer = Task { await calls.systemAnswer(id) }
        try await Task.sleep(for: .milliseconds(30))
        calls.finish(pending)
        let accepted = await answer.value
        XCTAssertFalse(accepted)
        XCTAssertFalse(calls.attachIncoming(pending, to: arrived, actions: actions()))
        XCTAssertFalse(calls.hasCall); XCTAssertEqual(driver.endedIDs, [id])
    }
    func testHangupReleasesEarlyAnswerBeforeWaitingForTransportCleanup() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        var cleanup: CheckedContinuation<Void, Never>?
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller",
            actions: actions(end: { await withCheckedContinuation { cleanup = $0 } })))
        let answer = Task { await calls.systemAnswer(id) }
        try await Task.sleep(for: .milliseconds(30))
        let end = Task { await calls.systemEnd(id) }
        try await ready { cleanup != nil }
        let accepted = await answer.value
        XCTAssertFalse(accepted)
        XCTAssertFalse(calls.attachIncoming(pending, to: arrived, actions: actions()))
        cleanup?.resume(); cleanup = nil
        let ended = await end.value
        XCTAssertTrue(ended); XCTAssertFalse(calls.hasCall)
    }
    func testWakeCannotAdoptAnotherServiceOrReplaceAnOrdinaryCall() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        let wrong = FamilySystemCallKey(service: .sip, id: arrived.id)
        XCTAssertFalse(calls.attachIncoming(pending, to: wrong, actions: actions()))
        XCTAssertTrue(calls.contains(pending)); calls.finish(pending)
        XCTAssertTrue(calls.track(arrived, name: "Ordinary call", incoming: true, actions: actions()))
        XCTAssertFalse(calls.attachIncoming(arrived, to: pending, actions: actions()))
        calls.finish(arrived)
        XCTAssertTrue(calls.setEnabled(false))
        XCTAssertFalse(calls.reserveIncoming(pending, id: id, name: "Disabled controls", actions: actions()))
        XCTAssertTrue(calls.track(arrived, name: "Ordinary disabled call", incoming: true, actions: actions()))
        XCTAssertFalse(calls.hasCall)
    }
    func testDuplicateWakeKeepsItsUUIDAndCannotBeAdoptedTwice() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        XCTAssertFalse(calls.reserveIncoming(pending, id: UUID(), name: "Unrelated wake", actions: actions()))
        try await ready { driver.reports == [id] }
        XCTAssertTrue(calls.attachIncoming(pending, to: arrived, actions: actions()))
        XCTAssertFalse(calls.attachIncoming(arrived, to: pending, actions: actions()))
        calls.finish(arrived)
        XCTAssertEqual(driver.reports, [id]); XCTAssertEqual(driver.endedIDs, [id])
    }
    func testTimedOutWakeRejectsEarlyAnswerWithoutEndingItsReplacement() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        let answer = Task { await calls.systemAnswer(id) }
        try await Task.sleep(for: .milliseconds(30))
        calls.systemActionTimedOut(id)
        let accepted = await answer.value
        XCTAssertFalse(accepted)
        try await ready { !calls.hasCall }
        XCTAssertTrue(calls.track(arrived, name: "New caller", incoming: true, actions: actions()))
        calls.systemActionTimedOut(id)
        XCTAssertTrue(calls.contains(arrived)); calls.finish(arrived)
    }
    func testRequiredPushWaitsForActualCallKitReportBeforeCompletion() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        driver.pauseReport = true
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        try await ready { driver.reportGate != nil }
        var completed: Bool?
        let acknowledgment = Task { let result = await calls.incomingReportCompleted(id); completed = result; return result }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNil(completed)
        XCTAssertTrue(calls.attachIncoming(pending, to: arrived, actions: actions()))
        driver.reportGate?.resume(); driver.reportGate = nil
        let accepted = await acknowledgment.value
        XCTAssertTrue(accepted)
        let alreadyReported = await calls.incomingReportCompleted(id)
        XCTAssertTrue(alreadyReported)
        calls.finish(arrived)
    }
    func testCancelledWakeReleasesReportAcknowledgmentBeforeLateReportReturns() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        driver.pauseReport = true
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        try await ready { driver.reportGate != nil }
        var completed: Bool?
        let acknowledgment = Task { let result = await calls.incomingReportCompleted(id); completed = result; return result }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNil(completed)
        calls.finish(pending)
        let accepted = await acknowledgment.value
        XCTAssertFalse(accepted)
        driver.reportGate?.resume(); driver.reportGate = nil
        XCTAssertFalse(calls.hasCall)
    }
    func testFailedCallKitReportCannotAcknowledgeARequiredPushAsReported() async throws {
        let driver = WakeHandoffDriver(), id = UUID()
        driver.failReport = true
        let calls = FamilySystemCalls(driver: driver, preferences: nil, enabled: true)
        XCTAssertTrue(calls.reserveIncoming(pending, id: id, name: "Approved caller", actions: actions()))
        let accepted = await calls.incomingReportCompleted(id)
        XCTAssertFalse(accepted)
        try await ready { !calls.hasCall }
        XCTAssertFalse(calls.error.isEmpty)
        let wrong = await calls.incomingReportCompleted(UUID())
        XCTAssertFalse(wrong)
    }

}
