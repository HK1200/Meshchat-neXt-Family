// SPDX-License-Identifier: 0BSD
import Combine
import Foundation

/// Serial provider enrollment for explicitly selected call contacts. Creating
/// this object neither registers PushKit nor starts the Reticulum runtime.
@MainActor final class NextCallWakeRegistration: ObservableObject {
    @Published private(set) var status = "Off"
    @Published private(set) var busy = false
    private struct Rejected: Error { let status: Int }
    private var current: NextCallWakeEnrollment?
    private var unreadable = false
    private var restored = false
    private var localEnabled = false
    private var token: Data?
    private var lastBody: Data?
    private var retryAfter = Date.distantPast
    private let store: any NextCallWakeEnrollmentStoring
    private let uploader: any NextPushUploading
    private let marker: @MainActor () throws -> Data?
    private let invalidateMarker: @MainActor () throws -> Void
    private let eligible: @MainActor () -> Bool
    private let permitted: @MainActor () -> Bool
    private let startDevice: @MainActor () -> Bool
    private let stopDevice: @MainActor () -> Void
    private let consentChanged: @MainActor () -> Void
    private let now: @MainActor () -> Date

    var configured: Bool { current != nil || unreadable }
    var stopping: Bool { current?.revoking == true }
    var needsReview: Bool { unreadable || current?.pausedForReview == true }
    var selectedCallers: [NextCallWakeEnrollment.Caller] { current?.selectedCallers ?? [] }
    var context: NextCallWakeContext? {
        guard localEnabled, eligible(), permitted(), let current,
              let value = try? marker() else { return nil }
        return current.context(installation: value)
    }

    init(store: any NextCallWakeEnrollmentStoring, uploader: any NextPushUploading,
         marker: @escaping @MainActor () throws -> Data?,
         invalidateMarker: @escaping @MainActor () throws -> Void,
         eligible: @escaping @MainActor () -> Bool,
         permitted: @escaping @MainActor () -> Bool,
         startDevice: @escaping @MainActor () -> Bool,
         stopDevice: @escaping @MainActor () -> Void,
         consentChanged: @escaping @MainActor () -> Void,
         now: @escaping @MainActor () -> Date = Date.init) {
        self.store = store; self.uploader = uploader
        self.marker = marker; self.invalidateMarker = invalidateMarker
        self.eligible = eligible; self.permitted = permitted
        self.startDevice = startDevice; self.stopDevice = stopDevice
        self.consentChanged = consentChanged; self.now = now
    }

    /// App-delegate cold-start entry after its registry/dispatcher are ready.
    /// No marker is created and no new contact receives consent here.
    func restore() {
        guard !restored else { return }
        restored = true
        do {
            guard let data = try store.load() else { return }
            guard data.count <= NextCallWakeEnrollment.maximumBytes else { throw NextCallWakeEnrollment.Invalid.record }
            let saved = try JSONDecoder().decode(NextCallWakeEnrollment.self, from: data)
            _ = try saved.validated(installation: saved.installation)
            current = saved
            if saved.revoking { disable(); return }
            guard let installation = try marker(), installation == saved.installation else {
                // Keychain survived app removal. Revoke, never reuse consent.
                disable(); return
            }
            guard saved.pausedForReview != true, permitted() else { pauseForReview(); return }
            guard eligible() else { status = "Call alerts require a push-enabled build."; return }
            localEnabled = true
            status = "Waiting for Apple call-alert registration"
            if !startDevice() { localEnabled = false; status = "Apple call-alert registration is unavailable." }
        } catch {
            localEnabled = false; unreadable = true
            status = "Call-alert setup could not be loaded. Review it before enabling alerts."
        }
    }

    /// The caller builds this only after native identity loading and a fresh
    /// private policy snapshot. A successful write precedes SDK registration.
    @discardableResult func enable(_ candidate: NextCallWakeEnrollment) -> Bool {
        activate(candidate, replacingPaused: false)
    }

    @discardableResult func resume(identity: NextCallWakeIdentity,
                                   callers: [NextCallWakeEnrollment.Caller],
                                   policyDigest: String, installation: Data) -> Bool {
        guard let saved = current else { return false }
        let reviewed = NextCallWakeEnrollment(provider: saved.provider, audience: saved.audience,
            enrollmentCode: saved.enrollmentCode, installation: installation,
            recipientPublicKey: identity.publicKey, agreementPrivateKey: identity.agreementPrivateKey,
            selectedCallers: callers, policyDigest: policyDigest)
        return activate(reviewed, replacingPaused: true)
    }

    private func activate(_ candidate: NextCallWakeEnrollment, replacingPaused: Bool) -> Bool {
        if !restored { restore() }
        let replaceable = replacingPaused && current?.pausedForReview == true && current?.mayBeRegistered == false
        guard (!configured || replaceable), !unreadable, !busy, eligible(), permitted(),
              !candidate.revoking, candidate.pausedForReview != true,
              !candidate.mayBeRegistered,
              let installation = try? marker(),
              let checked = try? candidate.validated(installation: installation) else {
            status = "Review the provider, selected callers and device permissions."; return false
        }
        do { try persist(checked) }
        catch { status = "Call-alert consent could not be saved."; return false }
        localEnabled = true; token = nil; lastBody = nil; retryAfter = .distantPast
        status = "Waiting for Apple call-alert registration"
        guard startDevice() else {
            pauseForReview(); status = "Apple call-alert registration is unavailable. Review and retry."; return false
        }
        return true
    }

    func receivedToken(_ value: Data?) {
        guard localEnabled, current?.revoking == false, current?.pausedForReview != true else { return }
        if let value, !(16...256).contains(value.count) { token = nil }
        else { token = value }
        retryAfter = .distantPast
        synchronize()
    }

    /// Any saved-call policy change requires a fresh explicit review. The
    /// selected public contacts stay available to prefill that review.
    func policyChanged(_ digest: String) {
        guard let saved = current, !saved.revoking, saved.pausedForReview != true, digest != saved.policyDigest else { return }
        pauseForReview()
    }

    func pauseForReview() {
        guard var saved = current, !saved.revoking else { return }
        localEnabled = false; token = nil
        saved.pausedForReview = true; current = saved
        stopDevice(); consentChanged()
        var durable = true
        do { try persist(saved) }
        catch { durable = (try? invalidateMarker()) != nil }
        status = durable ? "Call alerts paused. Review the allowed callers." :
            "Call alerts are paused for this session. Retry to save that choice."
        retryAfter = .distantPast; synchronize()
    }

    func disable() {
        // Reentrant token callbacks cannot regain consent during stop.
        let unknownProvider = unreadable && current == nil
        localEnabled = false; token = nil
        if var saved = current { saved.beginRevocation(); current = saved }
        stopDevice(); consentChanged()
        // A separate app-container tombstone prevents an old Keychain record
        // from restoring consent if the later Keychain update fails.
        let markerRemoved = (try? invalidateMarker()) != nil
        do {
            if let saved = current, saved.mayBeRegistered {
                try persist(saved)
                status = "Turning off call alerts"
            } else {
                try persist(nil); unreadable = false
                status = unknownProvider ? "Off locally. Review the previous provider setup." : "Off"; lastBody = nil
            }
        } catch {
            status = markerRemoved ? "Call alerts are off locally. Retry cleanup." :
                "Call alerts are off for this session. Retry to save that choice."
        }
        retryAfter = .distantPast; synchronize()
    }

    func retry() {
        retryAfter = .distantPast
        if current?.revoking == true || unreadable { disable() }
        else { synchronize() }
    }

    /// A rotated provider code may be used only to finish an existing
    /// revocation. It cannot revive the old private agreement or call consent.
    @discardableResult func updateRemovalCode(_ code: String) -> Bool {
        guard let saved = current, saved.revoking else { return false }
        var fresh = NextCallWakeEnrollment(provider: saved.provider, audience: saved.audience,
            enrollmentCode: code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
            installation: saved.installation, recipientPublicKey: saved.recipientPublicKey,
            agreementPrivateKey: nil, selectedCallers: saved.selectedCallers, policyDigest: saved.policyDigest)
        fresh.revoking = true; fresh.mayBeRegistered = saved.mayBeRegistered
        do { try persist(fresh) }
        catch { status = "The replacement removal code could not be saved."; return false }
        retryAfter = .distantPast; synchronize()
        return true
    }

    private func persist(_ value: NextCallWakeEnrollment?) throws {
        let data = try value.map { try $0.encoded(installation: $0.installation) }
        try store.save(data); current = value
    }

    private func synchronize() {
        guard var saved = current, !busy, now() >= retryAfter else { return }
        if !saved.revoking, saved.pausedForReview != true {
            guard eligible(), permitted(), let installation = try? marker(), installation == saved.installation else {
                pauseForReview(); return
            }
        }
        let removing = saved.revoking || saved.pausedForReview == true || token == nil
        guard !removing || saved.mayBeRegistered else { return }
        if !removing, !saved.mayBeRegistered {
            saved.mayBeRegistered = true
            do { try persist(saved) }
            catch {
                localEnabled = false; stopDevice(); consentChanged(); try? invalidateMarker()
                status = "Provider registration could not be saved. Review call alerts."; return
            }
        }
        guard let body = try? saved.subscription(token: removing ? nil : token),
              body != lastBody || removing else { return }
        let sent = saved
        let tokenAtSend = token
        busy = true
        Task { @MainActor in
            defer {
                busy = false
                // Only a changed state/token may bypass failure backoff.
                synchronize()
            }
            do {
                // A queued upload must not revive an old token or consent.
                guard current == sent, token == tokenAtSend else { return }
                if !removing {
                    guard eligible(), permitted(), let installation = try? marker(), installation == sent.installation else {
                        pauseForReview(); return
                    }
                }
                var request = URLRequest(url: sent.provider.appendingPathComponent("v1").appendingPathComponent("call-subscription"))
                request.httpMethod = "POST"; request.timeoutInterval = 12
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.setValue("Bearer " + sent.enrollmentCode, forHTTPHeaderField: "Authorization")
                request.httpBody = body
                let response = try await uploader.upload(request)
                guard response == 204 else { throw Rejected(status: response) }
                lastBody = body
                guard current == sent else { retryAfter = .distantPast; return }
                if sent.revoking {
                    do { try persist(nil) }
                    catch {
                        retryAfter = now().addingTimeInterval(30)
                        status = "Provider alerts removed. Retry local cleanup."; return
                    }
                    unreadable = false; lastBody = nil; status = "Off"
                } else if removing {
                    var fresh = sent; fresh.mayBeRegistered = false
                    do { try persist(fresh) }
                    catch {
                        retryAfter = now().addingTimeInterval(30)
                        status = "Provider alerts removed. Retry saving local preferences."; return
                    }
                    status = sent.pausedForReview == true ? "Call alerts paused. Review the allowed callers." :
                        "Waiting for Apple call-alert registration"
                } else { status = "On" }
            } catch {
                if current != sent || token != tokenAtSend { retryAfter = .distantPast }
                else {
                    retryAfter = now().addingTimeInterval(30)
                    if sent.revoking { status = "Off locally. Provider removal is pending." }
                    else if let rejection = error as? Rejected, [400, 401, 403, 404].contains(rejection.status) {
                        status = "Provider rejected call alerts. Check its address, enrollment code and call support."
                    } else { status = "Call-alert provider is unavailable. Retry when connected." }
                }
            }
        }
    }
}
