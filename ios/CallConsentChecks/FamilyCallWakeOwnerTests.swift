// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation
import XCTest

@MainActor private final class FamilyOwnerStore: NextCallWakeEnrollmentStoring {
    var value: Data?
    func load() throws -> Data? { value }
    func save(_ data: Data?) throws { value = data }
}
@MainActor private final class FamilyOwnerUploader: NextPushUploading {
    var requests: [URLRequest] = []
    func upload(_ request: URLRequest) async throws -> Int { requests.append(request); return 204 }
}
@MainActor private final class FamilyOwnerQuery: FamilyCallWakeQuerying {
    var requests = 0
    func response(_ request: URLRequest) async throws -> Data? { requests += 1; return nil }
}
@MainActor private final class FamilyOwnerReplay: NextCallWakeReplayStoring {
    var value: Data?
    func read() throws -> Data? { value }
    func write(_ data: Data) throws { value = data }
}
@MainActor private final class FamilyOwnerRuntime: FamilyCallWakeRuntime {
    var starts = 0
    func beginCallWake() async throws { starts += 1 }
}
@MainActor private final class FamilyOwnerRegistry: NextVoIPRegistryControlling {
    var listens: [Bool] = []
    var identifier: ObjectIdentifier { ObjectIdentifier(self) }
    func listen(_ enabled: Bool) { listens.append(enabled) }
}
@MainActor private final class FamilyOwnerGate: FamilyCallWakeArming {
    struct Arm { let call: UUID; let voice: String; let seconds: UInt32 }
    var arms: [Arm] = [], cancelled: [UUID] = []
    var resets = 0, accepts = true
    func arm(_ call: UUID, voice: String, seconds: UInt32) -> Bool {
        arms.append(Arm(call: call, voice: voice, seconds: seconds)); return accepts
    }
    func cancel(_ call: UUID) { cancelled.append(call) }
    func reset() { resets += 1 }
}
@MainActor private final class FamilyOwnerDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    var reports: [UUID] = [], names: [String] = [], endedIDs: [UUID] = []
    var hold = false
    var waiter: CheckedContinuation<Void, Error>?
    func incoming(_ id: UUID, name: String) async throws {
        reports.append(id); names.append(name)
        if hold { try await withCheckedThrowingContinuation { waiter = $0 } }
    }
    func start(_ id: UUID, name: String) async throws { }
    func answer(_ id: UUID) async throws { }
    func end(_ id: UUID) async throws { }
    func mute(_ id: UUID, muted: Bool) async throws { }
    func connected(_ id: UUID) { }
    func ended(_ id: UUID, failed: Bool) { endedIDs.append(id) }
    func release() { let old = waiter; waiter = nil; old?.resume(returning: ()) }
}

@MainActor private final class FamilyOwnerFixture {
    let directory: URL
    let store = FamilyOwnerStore(), uploader = FamilyOwnerUploader(), query = FamilyOwnerQuery()
    let replay = FamilyOwnerReplay(), runtime = FamilyOwnerRuntime(), registry = FamilyOwnerRegistry(), gate = FamilyOwnerGate()
    let driver = FamilyOwnerDriver()
    let system: FamilySystemCalls
    var owner: FamilyCallWakeOwner!
    var eligible = true, permitted = true, guardian = true
    var time: TimeInterval = 1000
    let raw = Data((0..<64).map(UInt8.init))
    var state: [String: Any]
    let voice: String
    init() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("family-owner-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory.appendingPathComponent("FamilyTCP"), withIntermediateDirectories: true)
        let key = try Self.key(Data((64..<128).map(UInt8.init)))
        voice = try FamilyCallWake.voiceAddress(publicKey: key)
        state = ["setup_complete": true, "voiceEnabled": true, "contacts": [["id": 7, "name": "Approved private caller",
            "identityPublicKey": key.map { String(format: "%02x", $0) }.joined(),
            "addresses": ["lxmf": FamilyCallWakePolicy.messagingAddress(key), "lxst": voice]]]]
        system = FamilySystemCalls(driver: driver, preferences: nil)
        try write(raw, name: "identity"); try saveState()
        owner = FamilyCallWakeOwner(system: system, runtime: runtime, gate: gate,
            directory: { [weak self] in try XCTUnwrap(self?.directory) },
            eligible: { [weak self] in self?.eligible == true }, permissions: { [weak self] in self?.permitted == true },
            store: store, uploader: uploader, query: query, replay: replay,
            registryFactory: { [weak self] _ in self!.registry },
            now: { [weak self] in Date(timeIntervalSince1970: self?.time ?? 1000) })
    }
    static func key(_ raw: Data) throws -> Data {
        try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: raw.prefix(32)).publicKey.rawRepresentation +
            Curve25519.Signing.PrivateKey(rawRepresentation: raw.suffix(32)).publicKey.rawRepresentation
    }
    func write(_ data: Data, name: String) throws {
        let file = directory.appendingPathComponent("FamilyTCP/" + name)
        try data.write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }
    func saveState() throws { try write(JSONSerialization.data(withJSONObject: state), name: "state.json") }
    func payload() throws -> Data {
        let path = try XCTUnwrap(Bundle(for: FamilyCallWakeOwnerTests.self).url(forResource: "call-wake-fixture", withExtension: "json"))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: path)) as? [String: Any])
        let vectors = try XCTUnwrap(json["vectors"] as? [String: Any])
        return try JSONSerialization.data(withJSONObject: XCTUnwrap(vectors["valid"]))
    }
    @discardableResult func enable(_ selected: Set<String>? = nil) -> Bool {
        owner.enable(provider: "https://example.invalid", audience: "private-calls", code: String(repeating: "a", count: 64),
                     selected: selected ?? [voice], guardianUnlocked: { self.guardian })
    }
    func close() { driver.release(); owner.close(); try? FileManager.default.removeItem(at: directory) }
}

@MainActor final class FamilyCallWakeOwnerTests: XCTestCase {
    private func ready(_ predicate: () -> Bool) async throws {
        for _ in 0..<1000 { if predicate() { return }; try await Task.sleep(for: .milliseconds(2)) }
        XCTFail("The isolated Family call-owner event did not finish"); throw URLError(.timedOut)
    }
    func testFamilyGuardianUnlockIsRequiredBeforeAnyEnrollmentOrInstallMarker() throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }
        f.guardian = false
        XCTAssertFalse(f.enable())
        XCTAssertNil(f.store.value); XCTAssertNil(try NextCallWakeInstallation.read(support: f.directory))
        XCTAssertTrue(f.registry.listens.isEmpty); XCTAssertTrue(f.uploader.requests.isEmpty)
    }
    func testFamilyPersonalBuildCannotEnrollARegistryOrArmItsNativeGate() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }
        f.eligible = false
        XCTAssertFalse(f.enable()); XCTAssertNil(f.store.value)
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 }
        XCTAssertTrue(f.gate.arms.isEmpty); XCTAssertEqual(f.runtime.starts, 0)
        XCTAssertTrue(f.registry.listens.isEmpty); XCTAssertTrue(f.uploader.requests.isEmpty)
    }
    func testFamilyApprovedWakeArmsBeforeItsOnlyRuntimeStartsAndReportsOnce() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }
        XCTAssertTrue(f.enable()); XCTAssertEqual(f.registry.listens, [true])
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 && f.runtime.starts == 1 }
        XCTAssertEqual(f.gate.arms.count, 1); XCTAssertEqual(f.gate.arms.first?.voice, f.voice)
        XCTAssertEqual(f.gate.arms.first?.seconds, 30)
        XCTAssertEqual(f.driver.reports.count, 1); XCTAssertEqual(f.driver.names, ["Approved private caller"])
        XCTAssertNotNil(f.owner.pendingIncoming(peer: f.voice))
    }
    func testFamilyNativeAdmissionFailureWaitsForCallKitAndNeverStartsPython() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }
        XCTAssertTrue(f.enable()); f.gate.accepts = false; f.driver.hold = true
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { f.driver.waiter != nil }
        XCTAssertEqual(complete, 0); XCTAssertEqual(f.runtime.starts, 0); XCTAssertFalse(f.system.hasCall)
        f.driver.release(); try await ready { complete == 1 }
        XCTAssertEqual(f.driver.reports.count, 1)
    }
    func testFamilyContactRemovalStopsTheRegistryAndRejectsItsOldSignedIntent() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }
        XCTAssertTrue(f.enable()); f.state["contacts"] = []; try f.saveState(); f.owner.refreshPolicy()
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 }
        XCTAssertTrue(f.owner.registration.needsReview)
        XCTAssertEqual(f.registry.listens, [true, false]); XCTAssertTrue(f.gate.arms.isEmpty)
        XCTAssertEqual(f.runtime.starts, 0)
    }
    func testFamilyIdentityReplacementCannotUseCachedPrivateEnrollment() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }
        XCTAssertTrue(f.enable()); try f.write(Data((64..<128).map(UInt8.init)), name: "identity")
        f.owner.refreshPolicy(); var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 }
        XCTAssertTrue(f.gate.arms.isEmpty); XCTAssertEqual(f.runtime.starts, 0)
        XCTAssertTrue(f.owner.registration.needsReview)
    }
    func testFamilyWakeTransportAdoptsItsPendingCallWithoutReportingTwice() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }; XCTAssertTrue(f.enable())
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 }
        let pending = try XCTUnwrap(f.owner.pendingIncoming(peer: f.voice))
        let actual = FamilySystemCallKey(service: .reticulum, id: "actual-private-transport")
        let actions = FamilySystemCallActions(prepareAudio: { true }, start: { true }, answer: { true }, end: {}, mute: { _ in true })
        XCTAssertTrue(f.system.attachIncoming(pending, to: actual, actions: actions))
        f.owner.attached(pending, to: actual)
        XCTAssertNil(f.owner.pendingIncoming(peer: f.voice))
        XCTAssertTrue(f.system.contains(actual)); XCTAssertEqual(f.driver.reports.count, 1)
        XCTAssertEqual(f.gate.cancelled, f.driver.reports)
    }
    func testFamilyLateHintCannotExtendTheRemainingSignedCallWindow() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }; XCTAssertTrue(f.enable()); f.time = 1028.8
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 }
        XCTAssertEqual(f.gate.arms.first?.seconds, 1)
    }
    func testFamilyLessThanOneSecondRemainingDoesNotArmOrStartTheRuntime() async throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }; XCTAssertTrue(f.enable()); f.time = 1029.5
        var complete = 0
        f.owner.receive(try f.payload(), mustReport: true) { complete += 1 }
        try await ready { complete == 1 }
        XCTAssertTrue(f.gate.arms.isEmpty); XCTAssertEqual(f.runtime.starts, 0)
    }
    func testFamilyReviewedRenameResumesOnlyWithFreshGuardianConsent() throws {
        let f = try FamilyOwnerFixture(); defer { f.close() }; XCTAssertTrue(f.enable())
        var contacts = try XCTUnwrap(f.state["contacts"] as? [[String: Any]])
        contacts[0]["name"] = "Reviewed private caller"; f.state["contacts"] = contacts; try f.saveState()
        f.owner.refreshPolicy(); XCTAssertTrue(f.owner.registration.needsReview)
        f.guardian = false
        XCTAssertFalse(f.owner.resume(selected: [f.voice], guardianUnlocked: { f.guardian }))
        f.guardian = true
        XCTAssertTrue(f.owner.resume(selected: [f.voice], guardianUnlocked: { f.guardian }))
        XCTAssertFalse(f.owner.registration.needsReview)
        XCTAssertEqual(f.owner.registration.selectedCallers.first?.name, "Reviewed private caller")
    }
}
