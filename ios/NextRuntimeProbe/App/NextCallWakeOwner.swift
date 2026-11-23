// SPDX-License-Identifier: 0BSD
import Foundation
import Combine

/// One native owner for explicit call-alert consent and its own PushKit registry.
/// Personal-signing builds never create a registry or contact a provider.
@MainActor final class NextCallWakeOwner {
    static let shared = NextCallWakeOwner()
    private var permissionObserver: AnyCancellable?
    private init() {
        permissionObserver = FamilySystemCalls.shared.$enabled.dropFirst().sink { [weak self] enabled in
            if !enabled { self?.registration.pauseForReview() }
            self?.dispatcher.refreshConsent()
        }
    }
    static var eligible: Bool {
        let value = Bundle.main.object(forInfoDictionaryKey: "NextPushEnvironment") as? String
        return value == "development" || value == "production"
    }
    static func support() throws -> URL {
        try FileManager.default.url(for: .applicationSupportDirectory,
            in: .userDomainMask, appropriateFor: nil, create: false)
    }
    lazy var registration: NextCallWakeRegistration = NextCallWakeRegistration(
        store: NextCallWakeEnrollmentKeychain(), uploader: NextPushHTTPS(),
        marker: { try NextCallWakeInstallation.read(support: Self.support()) },
        invalidateMarker: { try NextCallWakeInstallation.invalidate(support: Self.support()) },
        eligible: { Self.eligible }, permitted: { FamilySystemCalls.shared.enabled },
        startDevice: { [weak self] in self?.device.start() ?? false },
        stopDevice: { [weak self] in self?.device.stop() },
        consentChanged: { [weak self] in self?.dispatcher.refreshConsent() })
    private lazy var query: NextCallWakeQuery = NextCallWakeQuery()
    private lazy var dispatcher: NextCallWakeDispatcher = NextCallWakeDispatcher(system: .shared,
        router: .shared, runtime: NextRuntimeLauncher.shared,
        context: { [weak self] in self?.validatedContext() },
        cancellationCheck: { [weak self] wake, saved in
            guard let self, self.validatedContext() == saved,
                  let request = self.registration.callStateRequest(wake.call),
                  let data = try? await self.query.response(request),
                  self.validatedContext() == saved else { return false }
            return NextCallWakeCancellation.verified(data, wake: wake,
                audience: saved.audience, now: Int(Date().timeIntervalSince1970))
        })
    private lazy var device: NextVoIPPushDevice = NextVoIPPushDevice(
        delivery: { [weak self] payload, required, completion in
            guard let self else { completion(); return }
            self.dispatcher.receive(payload, mustReport: required, completion: completion)
        }, tokenChanged: { [weak self] token in self?.registration.receivedToken(token) })

    func restore() { registration.restore() }
    func policyChanged(_ digest: String) { registration.policyChanged(digest) }
    func refreshPermissions() {
        if !FamilySystemCalls.shared.enabled && registration.configured && !registration.stopping && !registration.needsReview { registration.pauseForReview() }
        registration.synchronizeIfDue()
        dispatcher.refreshConsent()
    }
    private func validatedContext() -> NextCallWakeContext? {
        guard let context = registration.context,
              let address = try? NextCallWakeIdentity.messagingAddress(publicKey: context.recipientPublicKey),
              let voice = try? FamilyCallWake.voiceAddress(publicKey: context.recipientPublicKey),
              let support = try? Self.support(),
              let identity = try? NextCallWakeIdentity.load(support: support,
                  expectedPublicKey: context.recipientPublicKey, address: address, voiceAddress: voice),
              identity.agreementPrivateKey == context.recipientPrivateKey else { return nil }
        return context
    }
}
