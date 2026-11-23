// SPDX-License-Identifier: 0BSD
import Combine
import Foundation

@MainActor protocol FamilyCallWakeRuntime: AnyObject {
    func beginCallWake() async throws
}
@MainActor protocol FamilyCallWakeArming {
    func arm(_ call: UUID, voice: String, seconds: UInt32) -> Bool
    func cancel(_ call: UUID)
    func reset()
}
@MainActor protocol FamilyCallWakeQuerying {
    func response(_ request: URLRequest) async throws -> Data?
}
extension NextCallWakeQuery: FamilyCallWakeQuerying { }

/// The production factory is in the live app. Model tests inject an isolated
/// directory, fake registry/runtime and no-network provider implementation.
@MainActor final class FamilyCallWakeOwner: ObservableObject {
    @Published private(set) var error = ""
    private let system: FamilySystemCalls
    private let runtime: any FamilyCallWakeRuntime
    private let gate: any FamilyCallWakeArming
    private let directory: @MainActor () throws -> URL
    private let eligibility: @MainActor () -> Bool
    private let permissions: @MainActor () -> Bool
    private let store: any NextCallWakeEnrollmentStoring
    private let uploader: any NextPushUploading
    private let query: any FamilyCallWakeQuerying
    private let replay: (any NextCallWakeReplayStoring)?
    private let factory: NextVoIPPushDevice.RegistryFactory?
    private let now: @MainActor () -> Date
    private var permissionObserver: AnyCancellable?
    var eligible: Bool { eligibility() }
    var permissionsReady: Bool { currentPermission() }

    init(system: FamilySystemCalls, runtime: any FamilyCallWakeRuntime,
         gate: any FamilyCallWakeArming, directory: @escaping @MainActor () throws -> URL,
         eligible: @escaping @MainActor () -> Bool, permissions: @escaping @MainActor () -> Bool,
         store: any NextCallWakeEnrollmentStoring, uploader: any NextPushUploading,
         query: any FamilyCallWakeQuerying, replay: (any NextCallWakeReplayStoring)? = nil,
         registryFactory: NextVoIPPushDevice.RegistryFactory? = nil,
         now: @escaping @MainActor () -> Date = Date.init) {
        self.system = system; self.runtime = runtime; self.gate = gate
        self.directory = directory; self.eligibility = eligible; self.permissions = permissions
        self.store = store; self.uploader = uploader; self.query = query
        self.replay = replay; self.factory = registryFactory; self.now = now
        permissionObserver = system.$enabled.dropFirst().sink { [weak self] enabled in
            guard let self else { return }
            if !enabled { self.gate.reset(); self.registration.pauseForReview() }
            self.dispatcher.refreshConsent()
        }
    }

    lazy var registration: NextCallWakeRegistration = NextCallWakeRegistration(
        store: store, uploader: uploader,
        marker: { [weak self] in guard let self else { return nil }; return try NextCallWakeInstallation.read(support: self.directory()) },
        invalidateMarker: { [weak self] in guard let self else { return }; try NextCallWakeInstallation.invalidate(support: self.directory()) },
        eligible: { [weak self] in self?.eligible == true },
        permitted: { [weak self] in self?.currentPermission() == true },
        startDevice: { [weak self] in self?.device.start() ?? false },
        stopDevice: { [weak self] in self?.gate.reset(); self?.device.stop() },
        consentChanged: { [weak self] in self?.dispatcher.refreshConsent() },
        validatePolicy: { [weak self] record in self?.validPolicy(record) == true }, now: now)
    private lazy var router: NextReticulumWakeRouter = NextReticulumWakeRouter(system: system, store: replay,
        now: { [weak self] in self?.now() ?? .distantFuture },
        retired: { [weak self] call in self?.gate.cancel(call) })
    private lazy var dispatcher: NextCallWakeDispatcher = NextCallWakeDispatcher(system: system,
        router: router, startRuntime: { [weak self] in try await self?.runtime.beginCallWake() },
        context: { [weak self] in self?.validatedContext() },
        admitted: { [weak self] wake, saved in
            guard let self, self.validatedContext() == saved else { return false }
            let remaining = min(30, Double(wake.issued) + 30 - self.now().timeIntervalSince1970)
            guard remaining.isFinite, remaining >= 1 else { return false }
            return self.gate.arm(wake.call, voice: wake.callerVoice, seconds: UInt32(remaining.rounded(.down)))
        },
        cancellationCheck: { [weak self] wake, saved in
            guard let self, self.validatedContext() == saved,
                  let request = self.registration.callStateRequest(wake.call),
                  let data = try? await self.query.response(request),
                  self.validatedContext() == saved else { return false }
            return NextCallWakeCancellation.verified(data, wake: wake,
                audience: saved.audience, now: Int(self.now().timeIntervalSince1970))
        })
    private lazy var device: NextVoIPPushDevice = NextVoIPPushDevice(
        eligible: { [weak self] in self?.eligible == true }, factory: factory,
        delivery: { [weak self] data, required, completion in
            guard let self else { completion(); return }
            self.dispatcher.receive(data, mustReport: required, completion: completion)
        }, tokenChanged: { [weak self] token in self?.registration.receivedToken(token) })

    func restore() { registration.restore() }
    func refreshPolicy() {
        if registration.configured && !registration.stopping && !registration.needsReview && registration.context == nil {
            gate.reset(); registration.pauseForReview()
        }
        registration.synchronizeIfDue()
        dispatcher.refreshConsent()
    }
    func pendingIncoming(peer: String) -> FamilySystemCallKey? {
        router.pendingIncoming(peer: peer, service: .reticulum)
    }
    func attached(_ pending: FamilySystemCallKey, to transport: FamilySystemCallKey) {
        router.attached(pending, to: transport)
    }
    func receive(_ data: Data, mustReport: Bool, completion: @escaping @MainActor () -> Void) {
        dispatcher.receive(data, mustReport: mustReport, completion: completion)
    }
    func availableCallers() -> [FamilyCallWakePolicy.Caller] {
        guard let support = try? directory(),
              let identity = try? FamilyCallWakePolicy.ownIdentity(support: support),
              let policy = try? FamilyCallWakePolicy.load(support: support) else { return [] }
        return policy.availableCallers(recipientPublicKey: identity.publicKey)
    }

    @discardableResult func enable(provider: String, audience: String, code: String,
                                   selected: Set<String>, guardianUnlocked: () -> Bool) -> Bool {
        guard guardianUnlocked(), eligible else {
            error = eligible ? "Unlock Guardian settings first." : "Apple call alerts require a push-enabled build."
            return false
        }
        do {
            let support = try directory(), identity = try FamilyCallWakePolicy.ownIdentity(support: support)
            let approval = try FamilyCallWakePolicy.load(support: support).approval(selected: selected, recipientPublicKey: identity.publicKey)
            guard let url = URL(string: provider.trimmingCharacters(in: .whitespacesAndNewlines)), guardianUnlocked() else { throw URLError(.badURL) }
            let installation = try NextCallWakeInstallation.createForOptIn(support: support)
            let candidate = NextCallWakeEnrollment(provider: url,
                audience: audience.trimmingCharacters(in: .whitespacesAndNewlines),
                enrollmentCode: code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
                installation: installation, recipientPublicKey: identity.publicKey,
                agreementPrivateKey: identity.agreementPrivateKey,
                selectedCallers: approval.callers.map { .init(publicKey: $0.publicKey, voiceAddress: $0.voiceAddress, name: $0.name) },
                policyDigest: approval.digest)
            let accepted = registration.enable(candidate)
            error = accepted ? "" : registration.status
            return accepted
        } catch { self.error = "Review the provider, verified contacts and calling permissions."; return false }
    }
    @discardableResult func resume(selected: Set<String>, guardianUnlocked: () -> Bool) -> Bool {
        guard guardianUnlocked(), eligible else { error = "Unlock Guardian settings in a push-enabled build first."; return false }
        do {
            let support = try directory(), own = try FamilyCallWakePolicy.ownIdentity(support: support)
            let approval = try FamilyCallWakePolicy.load(support: support).approval(selected: selected, recipientPublicKey: own.publicKey)
            let installation = try NextCallWakeInstallation.createForOptIn(support: support)
            let identity = NextCallWakeIdentity(agreementPrivateKey: own.agreementPrivateKey,
                publicKey: own.publicKey, address: own.messagingAddress, voiceAddress: try own.voiceAddress)
            guard guardianUnlocked() else { return false }
            let accepted = registration.resume(identity: identity,
                callers: approval.callers.map { .init(publicKey: $0.publicKey, voiceAddress: $0.voiceAddress, name: $0.name) },
                policyDigest: approval.digest, installation: installation)
            error = accepted ? "" : registration.status
            return accepted
        } catch { self.error = "Current guardian approvals could not be verified."; return false }
    }
    func disable(guardianUnlocked: () -> Bool) {
        guard guardianUnlocked() else { error = "Unlock Guardian settings first."; return }
        error = ""; gate.reset(); registration.disable()
    }
    func retry(guardianUnlocked: () -> Bool, removalCode: String? = nil) {
        guard guardianUnlocked() else { error = "Unlock Guardian settings first."; return }
        if let code = removalCode { _ = registration.updateRemovalCode(code) }
        else { registration.retry() }
    }
    func close() { gate.reset(); device.stop(); dispatcher.stop() }

    private func currentPermission() -> Bool {
        guard system.enabled, permissions(), let support = try? directory(),
              let policy = try? FamilyCallWakePolicy.load(support: support) else { return false }
        return policy.callingEnabled
    }
    private func validPolicy(_ record: NextCallWakeEnrollment) -> Bool {
        guard let support = try? directory(),
              let policy = try? FamilyCallWakePolicy.load(support: support),
              let fresh = try? policy.approval(selected: Set(record.selectedCallers.map(\.voiceAddress)), recipientPublicKey: record.recipientPublicKey),
              fresh.digest == record.policyDigest,
              let key = try? FamilyCallWakePolicy.identity(support: support, expectedPublicKey: record.recipientPublicKey),
              key == record.agreementPrivateKey else { return false }
        let selected = record.selectedCallers.sorted { $0.voiceAddress < $1.voiceAddress }
        return fresh.callers.count == selected.count && zip(fresh.callers, selected).allSatisfy { live, saved in
            live.publicKey == saved.publicKey && live.voiceAddress == saved.voiceAddress && live.name == saved.name
        }
    }
    private func validatedContext() -> NextCallWakeContext? {
        guard eligible, currentPermission(), let saved = registration.context,
              let support = try? directory(),
              let key = try? FamilyCallWakePolicy.identity(support: support, expectedPublicKey: saved.recipientPublicKey),
              key == saved.recipientPrivateKey else { return nil }
        return saved
    }
}
