import XCTest
import UIKit
import UserNotifications

@MainActor private final class PushMemory: NextPushStoring {
    var data: Data?
    var fail = false
    var writes = 0
    func load() -> Data? { data }
    func save(_ data: Data?) -> Bool {
        guard !fail else { return false }; writes += 1; self.data = data; return true
    }
}
@MainActor private final class PushDevice: NextPushDevice {
    var authorization = true
    var registrations = 0
    var unregistrations = 0
    var authorizations = 0
    var pause = false
    var waiting: CheckedContinuation<Bool, Never>?
    func authorize() async throws -> Bool {
        authorizations += 1
        if pause { return await withCheckedContinuation { waiting = $0 } }
        return authorization
    }
    func register() { registrations += 1 }
    func unregister() { unregistrations += 1 }
}
@MainActor private final class PushUpload: NextPushUploading {
    var requests: [URLRequest] = []
    var responses: [Int] = []
    var pause = false
    var waiting: CheckedContinuation<Int, Error>?
    func upload(_ request: URLRequest) async throws -> Int {
        requests.append(request)
        if pause && requests.count == 1 { return try await withCheckedThrowingContinuation { waiting = $0 } }
        return responses.isEmpty ? 204 : responses.removeFirst()
    }
}

final class PushRegistrationTests: XCTestCase {
    private let peer = String(repeating: "b2", count: 16)
    private let other = String(repeating: "c3", count: 16)
    private let secret = String(repeating: "11", count: 32)
    private let provider = "https://alerts.example.invalid"

    private func state(second: Bool = false, removed: Bool = false, own: String? = nil, mailbox: String? = nil) -> NextPushState {
        let first = NextPushContact(name: "Private contact", identityPublicKey: String(repeating: "d4", count: 64), addresses: ["lxmf": peer])
        let next = NextPushContact(name: "Other private contact", identityPublicKey: String(repeating: "e5", count: 64), addresses: ["lxmf": other])
        return NextPushState(address: own ?? String(repeating: "a1", count: 16),
                             mailbox: .init(address: mailbox ?? String(repeating: "ab", count: 16)),
                             contacts: removed ? [] : second ? [first, next] : [first])
    }
    @MainActor private func settle(_ service: NextPushRegistration) async throws {
        for _ in 0..<200 {
            if !service.busy { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTFail("The mock provider operation did not finish")
    }
    @MainActor private func ready(_ check: () -> Bool) async throws {
        for _ in 0..<200 {
            if check() { return }; try await Task.sleep(for: .milliseconds(5))
        }
        XCTFail("The private provider barrier was not reached")
    }
    private func body(_ request: URLRequest) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(request.httpBody)) as? [String: Any])
    }

    @MainActor func testPushDefaultsOffWithoutTokenRequestsOrStorageWrites() {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        service.refresh(state()); service.retry(); service.disable()
        XCTAssertFalse(service.configured); XCTAssertEqual(service.status, "Off")
        XCTAssertNil(store.data); XCTAssertEqual(store.writes, 0)
        XCTAssertEqual(device.registrations, 0); XCTAssertTrue(upload.requests.isEmpty)
    }

    @MainActor func testExplicitApprovalAndTokenRotationUploadOnlySelectedKeys() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(second: true), allowedAddresses: [peer], stillPermitted: { true })
        XCTAssertTrue(service.configured); XCTAssertEqual(device.registrations, 1)
        XCTAssertTrue(upload.requests.isEmpty)
        service.receivedToken(Data(repeating: 1, count: 32)); try await settle(service)
        XCTAssertEqual(service.status, "On"); XCTAssertEqual(upload.requests.count, 1)
        let request = try XCTUnwrap(upload.requests.first), payload = try body(request)
        XCTAssertEqual(request.url?.absoluteString, provider + "/v1/subscription")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + secret)
        XCTAssertEqual(Set(payload.keys), ["recipient", "token", "senders"])
        XCTAssertEqual(payload["senders"] as? [String], [String(repeating: "d4", count: 64)])
        XCTAssertEqual(payload["token"] as? String, String(repeating: "01", count: 32))
        XCTAssertFalse(request.url!.absoluteString.contains(secret))
        service.receivedToken(Data(repeating: 2, count: 32)); try await settle(service)
        XCTAssertEqual(upload.requests.count, 2)
        XCTAssertEqual(try body(upload.requests[1])["token"] as? String, String(repeating: "02", count: 32))
    }

    @MainActor func testContactRevokedDuringAuthorizationPreventsEnrollment() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload(); device.pause = true
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        let task = Task { await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true }) }
        try await ready { device.waiting != nil }
        service.refresh(state(removed: true)); device.waiting?.resume(returning: true)
        await task.value
        XCTAssertFalse(service.configured); XCTAssertNil(store.data)
        XCTAssertEqual(device.registrations, 0); XCTAssertTrue(upload.requests.isEmpty)
    }

    @MainActor func testMailboxChangedDuringAuthorizationPreventsEnrollment() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload(); device.pause = true
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        let task = Task { await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true }) }
        try await ready { device.waiting != nil }
        service.refresh(state(mailbox: String(repeating: "ff", count: 16)))
        device.waiting?.resume(returning: true); await task.value
        XCTAssertFalse(service.configured); XCTAssertNil(store.data); XCTAssertEqual(device.registrations, 0)
    }

    @MainActor func testTurningOffBeforeTokenRegistrationMakesNoProviderRequest() async {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.disable(); service.receivedToken(Data(repeating: 1, count: 32))
        XCTAssertEqual(service.status, "Off"); XCTAssertNil(store.data)
        XCTAssertEqual(device.unregistrations, 1); XCTAssertTrue(upload.requests.isEmpty)
    }

    @MainActor func testTurningOffDuringUploadRevokesBeforeClaimingOff() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload(); upload.pause = true
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data(repeating: 1, count: 32)); try await ready { upload.waiting != nil }
        service.disable(); XCTAssertTrue(service.stopping); XCTAssertNotNil(store.data)
        upload.waiting?.resume(returning: 204); try await settle(service)
        XCTAssertEqual(upload.requests.count, 2)
        let revocation = try body(upload.requests[1])
        XCTAssertTrue(revocation["token"] is NSNull); XCTAssertEqual(revocation["senders"] as? [String], [])
        XCTAssertEqual(service.status, "Off"); XCTAssertNil(store.data)
    }

    @MainActor func testChangingAllowedContactsDuringAnUploadPersistsAndSendsTheNewSelectionNext() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload(); upload.pause = true
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(second: true), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data(repeating: 1, count: 32)); try await ready { upload.waiting != nil }
        service.refresh(state(second: true))
        service.updateAllowedContacts([other], state: state(second: true), stillPermitted: { true })
        XCTAssertEqual(service.allowedAddresses, [other], "An explicit Save must not silently disappear behind an older upload")
        upload.waiting?.resume(returning: 204); try await settle(service)
        XCTAssertEqual(upload.requests.count, 2)
        XCTAssertEqual(try body(upload.requests[1])["senders"] as? [String], [String(repeating: "e5", count: 64)])
        let restored = NextPushRegistration(store: store, uploader: PushUpload(), device: PushDevice())
        XCTAssertEqual(restored.allowedAddresses, [other])
    }

    @MainActor func testPendingRevocationSurvivesRestartAndNeverRegistersAgain() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data(repeating: 1, count: 32)); try await settle(service)
        upload.responses = [503]; service.disable(); try await settle(service)
        XCTAssertTrue(service.stopping); XCTAssertNotNil(store.data)
        let restoredDevice = PushDevice(), restoredUpload = PushUpload()
        let restored = NextPushRegistration(store: store, uploader: restoredUpload, device: restoredDevice)
        restored.refresh(state()); try await settle(restored)
        XCTAssertEqual(restoredDevice.registrations, 0); XCTAssertEqual(restoredUpload.requests.count, 1)
        XCTAssertTrue(try body(restoredUpload.requests[0])["token"] is NSNull)
        XCTAssertEqual(restored.status, "Off"); XCTAssertNil(store.data)
    }

    @MainActor func testKeychainFailureAndDeniedAuthorizationCannotStartRegistration() async {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload(); store.fail = true
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        XCTAssertFalse(service.configured); XCTAssertEqual(device.registrations, 0)
        store.fail = false; device.authorization = false
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        XCTAssertFalse(service.configured); XCTAssertNil(store.data); XCTAssertTrue(upload.requests.isEmpty)
    }

    @MainActor func testFailedProviderRemainsPendingAndExplicitRetryWorks() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload(); upload.responses = [503, 204]
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data(repeating: 1, count: 32)); try await settle(service)
        XCTAssertNotEqual(service.status, "On"); XCTAssertNotNil(store.data)
        service.refresh(state()); XCTAssertEqual(upload.requests.count, 1)
        service.retry(); try await settle(service)
        XCTAssertEqual(service.status, "On"); XCTAssertEqual(upload.requests.count, 2)
    }

    @MainActor func testUnapprovedContactInvalidProviderAndBadTokenNeverUpload() async {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        for address in ["http://example.invalid", "https://name:pass@example.invalid", "https://example.invalid/path", "https://example.invalid:0"] {
            await service.enable(provider: address, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        }
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [other], stillPermitted: { true })
        XCTAssertEqual(device.authorizations, 0); XCTAssertNil(store.data)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data()); XCTAssertTrue(upload.requests.isEmpty)
        service.disable(); XCTAssertEqual(service.status, "Off")
    }

    @MainActor func testIdentityChangeRevokesTheOriginalRecipient() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data(repeating: 1, count: 32)); try await settle(service)
        service.refresh(state(own: String(repeating: "ff", count: 16))); try await settle(service)
        XCTAssertEqual(service.status, "Off")
        XCTAssertEqual(try body(upload.requests[1])["recipient"] as? String, state().address)
        XCTAssertTrue(try body(upload.requests[1])["token"] is NSNull)
    }

    @MainActor func testContactRemovalsWinOverStaleSelectionAndNewContactsNeedConsent() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        service.receivedToken(Data(repeating: 1, count: 32)); try await settle(service)
        service.refresh(state(second: true)); XCTAssertEqual(upload.requests.count, 1)
        service.updateAllowedContacts([other], state: state(second: true), stillPermitted: { true }); try await settle(service)
        XCTAssertEqual(try body(upload.requests[1])["senders"] as? [String], [String(repeating: "e5", count: 64)])
        service.refresh(state(removed: true)); try await settle(service)
        XCTAssertEqual(try body(upload.requests[2])["senders"] as? [String], [])
        service.updateAllowedContacts([peer], state: state(), stillPermitted: { true })
        XCTAssertEqual(upload.requests.count, 3)
    }
}

@MainActor private final class PushNotices: NextAlertPosting {
    func authorization() async -> UNAuthorizationStatus { .authorized }
    func lockScreen() async -> UNNotificationSetting { .enabled }
    func requestAuthorization() async throws -> Bool { true }
    func post(_ notice: NextUnreadNotice) async throws {}
}

extension PushRegistrationTests {
    @MainActor func testPushHintAcknowledgementPreservesANewerHintAndIgnoresAlertsAfterOff() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        let suite = "next-push-notices." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let alerts = NextMessageAlerts(center: PushNotices(), defaults: defaults, push: service)
        XCTAssertFalse(alerts.requestMailboxSync(openInbox: true))
        XCTAssertFalse(alerts.mailboxInboxRequested)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        XCTAssertTrue(alerts.requestMailboxSync(openInbox: true))
        let first = alerts.mailboxSyncGeneration
        XCTAssertTrue(alerts.mailboxInboxRequested)
        alerts.consumedMailboxInbox(); XCTAssertFalse(alerts.mailboxInboxRequested)
        XCTAssertTrue(alerts.requestMailboxSync())
        alerts.consumedMailboxSync(through: first)
        XCTAssertTrue(alerts.mailboxSyncRequested, "An in-flight retrieval must not swallow a later alert")
        alerts.consumedMailboxSync(through: alerts.mailboxSyncGeneration + 1)
        XCTAssertTrue(alerts.mailboxSyncRequested, "An unissued generation cannot be acknowledged")
        alerts.consumedMailboxSync(through: alerts.mailboxSyncGeneration)
        XCTAssertFalse(alerts.mailboxSyncRequested)
        service.disable()
        XCTAssertFalse(alerts.requestMailboxSync(openInbox: true))
        XCTAssertFalse(alerts.mailboxInboxRequested)
    }

    @MainActor func testApplicationDelegateForwardsTokenRotationAndDoesNotReviveDisabledEnrollment() async throws {
        let store = PushMemory(), device = PushDevice(), upload = PushUpload()
        let service = NextPushRegistration(store: store, uploader: upload, device: device)
        let suite = "next-push-delegate." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let alerts = NextMessageAlerts(center: PushNotices(), defaults: defaults, push: service)
        await service.enable(provider: provider, secret: secret, state: state(), allowedAddresses: [peer], stillPermitted: { true })
        alerts.application(UIApplication.shared, didRegisterForRemoteNotificationsWithDeviceToken: Data(repeating: 1, count: 32))
        try await settle(service)
        XCTAssertEqual(service.status, "On")
        XCTAssertEqual(try body(XCTUnwrap(upload.requests.first))["token"] as? String, String(repeating: "01", count: 32))
        alerts.application(UIApplication.shared, didRegisterForRemoteNotificationsWithDeviceToken: Data(repeating: 2, count: 32))
        try await settle(service)
        XCTAssertEqual(upload.requests.count, 2)
        service.disable(); try await settle(service)
        XCTAssertEqual(service.status, "Off")
        let count = upload.requests.count
        alerts.application(UIApplication.shared, didRegisterForRemoteNotificationsWithDeviceToken: Data(repeating: 3, count: 32))
        alerts.application(UIApplication.shared, didFailToRegisterForRemoteNotificationsWithError: URLError(.notConnectedToInternet))
        try await settle(service)
        XCTAssertEqual(upload.requests.count, count)
        XCTAssertEqual(service.status, "Off")
    }
}
