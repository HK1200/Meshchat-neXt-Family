// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

@MainActor private final class CallConsentStore: NextCallWakeEnrollmentStoring {
    enum Failure: Error { case locked }
    var value: Data?
    var failLoad = false, failSave = false
    func load() throws -> Data? { if failLoad { throw Failure.locked }; return value }
    func save(_ data: Data?) throws { if failSave { throw Failure.locked }; value = data }
}
@MainActor private final class CallConsentUploader: NextPushUploading {
    var requests: [URLRequest] = []
    var hold = false, fail = false, closed = false
    var response = 204
    var pending: [CheckedContinuation<Int, Error>] = []
    func upload(_ request: URLRequest) async throws -> Int {
        guard !closed else { throw CancellationError() }
        requests.append(request)
        if fail { throw URLError(.notConnectedToInternet) }
        if hold { return try await withCheckedThrowingContinuation { pending.append($0) } }
        return response
    }
    func release(_ result: Result<Int, Error> = .success(204)) {
        let values = pending; pending.removeAll()
        for value in values { value.resume(with: result) }
    }
    func close() { closed = true; release(.failure(CancellationError())) }
}
@MainActor private final class CallConsentFixture {
    let store = CallConsentStore(), uploader = CallConsentUploader()
    var marker: Data? = Data(repeating: 7, count: 32)
    var eligible = true, permitted = true
    var failInvalidate = false
    var starts = 0, stops = 0, changes = 0
    var time: TimeInterval = 1000
    var policyValid = true
    var controller: NextCallWakeRegistration!
    init() {
        controller = NextCallWakeRegistration(store: store, uploader: uploader,
            marker: { [weak self] in self?.marker },
            invalidateMarker: { [weak self] in
                if self?.failInvalidate == true { throw URLError(.cannotWriteToFile) }
                self?.marker = nil
            },
            eligible: { [weak self] in self?.eligible == true },
            permitted: { [weak self] in self?.permitted == true },
            startDevice: { [weak self] in self?.starts += 1; return true },
            stopDevice: { [weak self] in self?.stops += 1 },
            consentChanged: { [weak self] in self?.changes += 1 },
            validatePolicy: { [weak self] _ in self?.policyValid == true },
            now: { [weak self] in Date(timeIntervalSince1970: self?.time ?? 1000) })
    }
    func record() throws -> NextCallWakeEnrollment {
        let agreement = Curve25519.KeyAgreement.PrivateKey()
        let publicKey = agreement.publicKey.rawRepresentation + Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        let peer = Curve25519.KeyAgreement.PrivateKey().publicKey.rawRepresentation + Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        return NextCallWakeEnrollment(provider: URL(string: "https://example.invalid")!, audience: "private-calls",
            enrollmentCode: String(repeating: "a", count: 64), installation: try XCTUnwrap(marker),
            recipientPublicKey: publicKey, agreementPrivateKey: agreement.rawRepresentation,
            selectedCallers: [.init(publicKey: peer, voiceAddress: try FamilyCallWake.voiceAddress(publicKey: peer), name: "Selected caller")],
            policyDigest: String(repeating: "b", count: 64))
    }
    func saved() throws -> NextCallWakeEnrollment {
        try JSONDecoder().decode(NextCallWakeEnrollment.self, from: XCTUnwrap(store.value))
    }
    func body(_ index: Int) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(uploader.requests[index].httpBody)) as? [String: Any])
    }
    func close() { uploader.close() }
}

@MainActor final class CallWakeRegistrationTests: XCTestCase {
    private func ready(_ condition: @escaping @MainActor () -> Bool) async throws {
        for _ in 0..<3000 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(1))
        }
        throw URLError(.timedOut)
    }
    func testProviderSharingExposesOnlyPublicSetupAndDisappearsOnDisable() throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertNil(f.controller.recipientProvider); XCTAssertNil(f.controller.recipientAudience)
        let record = try f.record()
        XCTAssertTrue(f.controller.enable(record))
        XCTAssertEqual(f.controller.recipientProvider, "https://example.invalid")
        XCTAssertEqual(f.controller.recipientAudience, "private-calls")
        f.controller.disable()
        XCTAssertNil(f.controller.recipientProvider); XCTAssertNil(f.controller.recipientAudience)
    }

    func testCallStateLookupRequiresCurrentConsentAndContainsNoPrivateIdentity() throws {
        let f = CallConsentFixture(); defer { f.close() }
        let call = UUID()
        XCTAssertNil(f.controller.callStateRequest(call))
        let record = try f.record()
        XCTAssertTrue(f.controller.enable(record))
        let request = try XCTUnwrap(f.controller.callStateRequest(call))
        XCTAssertEqual(request.url?.absoluteString, "https://example.invalid/v1/call-state")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + record.enrollmentCode)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(request.httpBody)) as? [String: String])
        XCTAssertEqual(Set(body.keys), ["owner", "call"])
        XCTAssertEqual(body["owner"], try NextCallWakeIdentity.messagingAddress(publicKey: record.recipientPublicKey))
        XCTAssertEqual(body["call"], call.uuidString.lowercased().replacingOccurrences(of: "-", with: ""))
        f.controller.disable()
        XCTAssertNil(f.controller.callStateRequest(call))
    }
    func testPermissionOrInstallMarkerLossImmediatelyPreventsStateLookup() throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        XCTAssertNotNil(f.controller.callStateRequest(UUID()))
        f.permitted = false
        XCTAssertNil(f.controller.callStateRequest(UUID()))
        f.permitted = true; f.marker = nil
        XCTAssertNil(f.controller.callStateRequest(UUID()))
    }

    func testPolicyPauseCanUseTheInstallMarkerWhenKeychainWritingFails() throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.store.failSave = true
        XCTAssertTrue(f.controller.pauseForReview())
        XCTAssertNil(f.marker)
        XCTAssertNil(f.controller.context)
    }
    func testPolicyPauseRefusesToAuthorizeAnEditWhenBothDurableWritesFail() throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.store.failSave = true; f.failInvalidate = true
        XCTAssertFalse(f.controller.pauseForReview())
        XCTAssertNotNil(f.marker)
        XCTAssertNil(f.controller.context)
        XCTAssertNotEqual(try f.saved().pausedForReview, true)
    }
    func testAnUnreadableOldEnrollmentStillRequiresDurableRevocationBeforePolicyEdits() {
        let f = CallConsentFixture(); defer { f.close() }
        f.store.failLoad = true; f.failInvalidate = true
        f.controller.restore()
        XCTAssertFalse(f.controller.pauseForReview())
        f.failInvalidate = false
        XCTAssertTrue(f.controller.pauseForReview())
        XCTAssertNil(f.marker)
    }

    func testNothingRegistersWithoutConsentOrInAnIneligibleBuild() throws {
        let f = CallConsentFixture(); defer { f.close() }
        f.controller.restore()
        XCTAssertEqual(f.starts, 0); XCTAssertNil(f.controller.context)
        f.eligible = false
        XCTAssertFalse(f.controller.enable(try f.record()))
        XCTAssertNil(f.store.value); XCTAssertEqual(f.starts, 0); XCTAssertTrue(f.uploader.requests.isEmpty)
    }
    func testConsentIsSavedBeforeSDKRegistrationAndProviderUploadContainsOnlyPublicFields() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        XCTAssertNotNil(f.store.value); XCTAssertEqual(f.starts, 1); XCTAssertNotNil(f.controller.context)
        f.uploader.hold = true
        f.controller.receivedToken(Data(repeating: 1, count: 32))
        try await ready { f.uploader.pending.count == 1 }
        XCTAssertTrue(try f.saved().mayBeRegistered)
        XCTAssertEqual(Set(try f.body(0).keys), ["recipient_key", "token", "callers"])
        XCTAssertEqual(f.uploader.requests[0].url?.absoluteString, "https://example.invalid/v1/call-subscription")
        XCTAssertEqual(f.uploader.requests[0].value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "a", count: 64))
        f.uploader.hold = false; f.uploader.release()
        try await ready { !f.controller.busy }
        XCTAssertEqual(f.controller.status, "On")
    }
    func testTurnOffBeforeAQueuedUploadCannotRegisterTheRevokedToken() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.controller.receivedToken(Data(repeating: 1, count: 32))
        f.controller.disable()
        XCTAssertNil(f.controller.context); XCTAssertNil(try f.saved().agreementPrivateKey)
        try await ready { !f.controller.configured && !f.controller.busy }
        XCTAssertEqual(f.uploader.requests.count, 1)
        XCTAssertTrue(try f.body(0)["token"] is NSNull)
        XCTAssertEqual(try f.body(0)["callers"] as? [String], [])
    }
    func testTurnOffDuringAnInFlightRegistrationRemovesItAfterward() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.uploader.hold = true; f.controller.receivedToken(Data(repeating: 1, count: 32))
        try await ready { f.uploader.pending.count == 1 }
        f.controller.disable()
        XCTAssertNil(f.controller.context); XCTAssertNil(try f.saved().agreementPrivateKey)
        XCTAssertNil(f.marker); XCTAssertGreaterThan(f.stops, 0)
        f.uploader.hold = false; f.uploader.release()
        try await ready { !f.controller.configured && !f.controller.busy }
        XCTAssertEqual(f.uploader.requests.count, 2)
        XCTAssertTrue(try f.body(1)["token"] is NSNull); XCTAssertNil(f.store.value)
    }
    func testTokenRotationIsSerialAndTheLatestTokenSurvivesAnEarlierFailure() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.uploader.hold = true; f.controller.receivedToken(Data(repeating: 1, count: 32))
        try await ready { f.uploader.pending.count == 1 }
        f.controller.receivedToken(Data(repeating: 2, count: 32))
        XCTAssertEqual(f.uploader.requests.count, 1)
        f.uploader.hold = false; f.uploader.release(.failure(URLError(.networkConnectionLost)))
        try await ready { f.uploader.requests.count == 2 && !f.controller.busy }
        XCTAssertEqual(try f.body(1)["token"] as? String, String(repeating: "02", count: 32))
        XCTAssertEqual(f.controller.status, "On")
    }
    func testPolicyChangePausesImmediatelyAndKeepsExplicitSelectionsForReview() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        let value = try f.record()
        XCTAssertTrue(f.controller.enable(value))
        f.controller.policyChanged(String(repeating: "c", count: 64))
        XCTAssertNil(f.controller.context); XCTAssertTrue(f.controller.needsReview)
        XCTAssertEqual(f.controller.selectedCallers, value.selectedCallers)
        let writes = f.changes
        f.controller.policyChanged(String(repeating: "c", count: 64))
        XCTAssertEqual(f.changes, writes)
        XCTAssertTrue(f.uploader.requests.isEmpty)
        let identity = NextCallWakeIdentity(agreementPrivateKey: try XCTUnwrap(value.agreementPrivateKey),
            publicKey: value.recipientPublicKey, address: "", voiceAddress: "")
        XCTAssertTrue(f.controller.resume(identity: identity, callers: [], policyDigest: String(repeating: "c", count: 64), installation: try XCTUnwrap(f.marker)))
        XCTAssertNotNil(f.controller.context); XCTAssertTrue(f.controller.selectedCallers.isEmpty)
    }
    func testAChangedInstallationRevokesTheOldKeychainConsentInsteadOfRestoringIt() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        var saved = try f.record(); saved.mayBeRegistered = true
        f.store.value = try saved.encoded(installation: saved.installation)
        f.marker = Data(repeating: 8, count: 32)
        f.uploader.hold = true; f.controller.restore()
        XCTAssertEqual(f.starts, 0); XCTAssertNil(f.controller.context)
        XCTAssertNil(try f.saved().agreementPrivateKey); XCTAssertTrue(try f.saved().revoking)
        try await ready { f.uploader.pending.count == 1 }
        XCTAssertTrue(try f.body(0)["token"] is NSNull)
        f.uploader.hold = false; f.uploader.release()
        try await ready { !f.controller.configured && !f.controller.busy }
    }
    func testLockedKeychainAndFailedWritesCannotSilentlyEnableAlerts() throws {
        let f = CallConsentFixture(); defer { f.close() }
        f.store.failLoad = true; f.controller.restore()
        XCTAssertTrue(f.controller.needsReview); XCTAssertEqual(f.starts, 0)
        XCTAssertFalse(f.controller.enable(try f.record()))
        f.store.failLoad = false; f.controller.disable()
        f.marker = Data(repeating: 9, count: 32); f.store.failSave = true
        XCTAssertFalse(f.controller.enable(try f.record()))
        XCTAssertEqual(f.starts, 0); XCTAssertNil(f.controller.context)
    }
    func testProviderRemovalFailureStaysLocallyOffAcrossRestartAndCanRetry() async throws {
        let first = CallConsentFixture(), second = CallConsentFixture()
        defer { first.close(); second.close() }
        var saved = try first.record(); saved.mayBeRegistered = true
        first.store.value = try saved.encoded(installation: saved.installation)
        first.controller.restore(); first.uploader.fail = true; first.controller.disable()
        try await ready { first.uploader.requests.count == 1 && !first.controller.busy }
        XCTAssertNil(first.controller.context); XCTAssertNil(try first.saved().agreementPrivateKey)
        second.store.value = first.store.value; second.marker = nil; second.uploader.fail = true
        second.controller.restore()
        try await ready { second.uploader.requests.count == 1 && !second.controller.busy }
        XCTAssertEqual(second.starts, 0); XCTAssertNil(second.controller.context)
        second.uploader.fail = false; second.controller.retry()
        try await ready { !second.controller.configured && !second.controller.busy }
        XCTAssertNil(second.store.value)
    }
    func testMarkerRevocationPreventsAnOldRecordReturningAfterAKeychainWriteFailure() throws {
        let first = CallConsentFixture(), second = CallConsentFixture()
        defer { first.close(); second.close() }
        XCTAssertTrue(first.controller.enable(try first.record()))
        first.store.failSave = true; first.controller.disable()
        XCTAssertNil(first.marker); XCTAssertNil(first.controller.context)
        XCTAssertNotNil(first.store.value)
        second.store.value = first.store.value; second.marker = nil; second.controller.restore()
        XCTAssertEqual(second.starts, 0); XCTAssertNil(second.controller.context)
        XCTAssertNil(second.store.value)
    }
    func testCachedConsentRestoresOnlyTheSavedSelectionAndStartsItsRegistryOnce() throws {
        let f = CallConsentFixture(); defer { f.close() }
        let value = try f.record()
        f.store.value = try value.encoded(installation: value.installation)
        XCTAssertEqual(f.starts, 0)
        f.controller.restore(); f.controller.restore()
        XCTAssertEqual(f.starts, 1)
        XCTAssertEqual(f.controller.context?.approvedNames, Dictionary(uniqueKeysWithValues: value.selectedCallers.map { ($0.voiceAddress, $0.name) }))
        XCTAssertTrue(f.uploader.requests.isEmpty)
    }
    func testPermissionLossBeforeAQueuedUploadCannotRegisterItsToken() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.controller.receivedToken(Data(repeating: 1, count: 32)); f.permitted = false
        try await ready { f.controller.needsReview && !f.controller.busy }
        XCTAssertNil(f.controller.context)
        XCTAssertEqual(f.uploader.requests.count, 1)
        XCTAssertTrue(try f.body(0)["token"] is NSNull)
    }

    func testProviderRejectionIsDistinctFromAConnectionFailure() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.uploader.response = 403; f.controller.receivedToken(Data(repeating: 1, count: 32))
        try await ready { !f.controller.busy }
        XCTAssertTrue(f.controller.status.contains("Provider rejected"))
        f.uploader.fail = true; f.controller.retry()
        try await ready { f.uploader.requests.count == 2 && !f.controller.busy }
        XCTAssertTrue(f.controller.status.contains("unavailable"))
    }
    func testRotatedCodeCanFinishRemovalButNeverRestoreConsent() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        XCTAssertFalse(f.controller.updateRemovalCode(String(repeating: "c", count: 64)))
        f.uploader.response = 403; f.controller.receivedToken(Data(repeating: 1, count: 32))
        try await ready { !f.controller.busy }
        f.controller.disable()
        try await ready { f.uploader.requests.count == 2 && !f.controller.busy }
        XCTAssertNil(f.controller.context)
        f.uploader.response = 204
        XCTAssertTrue(f.controller.updateRemovalCode(String(repeating: "c", count: 64)))
        try await ready { !f.controller.configured && !f.controller.busy }
        XCTAssertEqual(f.uploader.requests.last?.value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "c", count: 64))
        XCTAssertTrue(try f.body(2)["token"] is NSNull); XCTAssertNil(f.controller.context)
    }

    func testRegistrationJournalFailureSendsNoTokenAndKeepsRecoveryInReview() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.store.failSave = true
        f.controller.receivedToken(Data(repeating: 1, count: 32))
        XCTAssertTrue(f.uploader.requests.isEmpty); XCTAssertNil(f.controller.context)
        XCTAssertTrue(f.controller.needsReview); XCTAssertNil(f.marker)
        f.store.failSave = false; f.controller.retry()
        try await ready { f.uploader.requests.count == 1 && !f.controller.busy }
        XCTAssertTrue(try f.body(0)["token"] is NSNull)
        XCTAssertTrue(f.controller.needsReview); XCTAssertNil(f.controller.context)
    }

    func testColdRefreshDoesNotUnregisterBeforeAppleReturnsItsToken() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        var record = try f.record(); record.mayBeRegistered = true
        f.store.value = try record.encoded(installation: record.installation)
        f.controller.restore()
        for _ in 0..<5 { f.controller.synchronizeIfDue() }
        XCTAssertFalse(f.controller.busy)
        XCTAssertTrue(f.uploader.requests.isEmpty)
        f.controller.receivedToken(Data(repeating: 4, count: 32))
        try await ready { f.uploader.requests.count == 1 && !f.controller.busy }
        XCTAssertEqual(try f.body(0)["token"] as? String, String(repeating: "04", count: 32))
    }
    func testExplicitTokenInvalidationStillRemovesTheRegisteredToken() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.controller.receivedToken(Data(repeating: 4, count: 32))
        try await ready { f.uploader.requests.count == 1 && !f.controller.busy }
        f.controller.receivedToken(nil)
        try await ready { f.uploader.requests.count == 2 && !f.controller.busy }
        XCTAssertTrue(try f.body(1)["token"] is NSNull)
    }
    func testAutomaticProviderRetryHonorsBackoffAndRecoversWithoutAnotherToken() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.uploader.fail = true; f.controller.receivedToken(Data(repeating: 4, count: 32))
        try await ready { f.uploader.requests.count == 1 && !f.controller.busy }
        f.uploader.fail = false; f.time = 1029; f.controller.synchronizeIfDue()
        XCTAssertFalse(f.controller.busy)
        XCTAssertEqual(f.uploader.requests.count, 1)
        f.time = 1030; f.controller.synchronizeIfDue()
        try await ready { f.uploader.requests.count == 2 && !f.controller.busy }
        XCTAssertEqual(try f.body(1)["token"] as? String, String(repeating: "04", count: 32))
    }

    func testFreshEnrollmentMustPassItsExplicitPolicyValidator() throws {
        let f = CallConsentFixture(); defer { f.close() }
        f.policyValid = false
        XCTAssertFalse(f.controller.enable(try f.record()))
        XCTAssertNil(f.store.value); XCTAssertEqual(f.starts, 0)
    }
    func testSavedPolicyLossBeforeQueuedUploadCanOnlyRemoveTheToken() async throws {
        let f = CallConsentFixture(); defer { f.close() }
        XCTAssertTrue(f.controller.enable(try f.record()))
        f.controller.receivedToken(Data(repeating: 4, count: 32)); f.policyValid = false
        try await ready { f.controller.needsReview && !f.controller.busy }
        XCTAssertNil(f.controller.context)
        XCTAssertEqual(f.uploader.requests.count, 1)
        XCTAssertTrue(try f.body(0)["token"] is NSNull)
    }

}
