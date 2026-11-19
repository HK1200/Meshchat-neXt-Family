import AVFoundation
import CallKit
import Foundation

@MainActor
final class FamilyCallKitDriver: NSObject, FamilySystemCallDriver, CXProviderDelegate {
    weak var events: (any FamilySystemCallEvents)?
    private let controller = CXCallController()
    private let provider: CXProvider

    override init() {
        let displayName = Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "neXt Family"
        let configuration = CXProviderConfiguration(localizedName: displayName)
        configuration.supportsVideo = false
        configuration.maximumCallGroups = 1
        configuration.maximumCallsPerCallGroup = 1
        configuration.supportedHandleTypes = [.generic]
        configuration.includesCallsInRecents = false
        provider = CXProvider(configuration: configuration)
        super.init()
        provider.setDelegate(self, queue: .main)
    }

    private func update(_ name: String) -> CXCallUpdate {
        let update = CXCallUpdate()
        update.localizedCallerName = name
        update.remoteHandle = CXHandle(type: .generic, value: name)
        update.hasVideo = false
        update.supportsHolding = false
        update.supportsGrouping = false
        update.supportsUngrouping = false
        update.supportsDTMF = false
        return update
    }

    func incoming(_ id: UUID, name: String) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            provider.reportNewIncomingCall(with: id, update: update(name)) { error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume() }
            }
        }
    }

    func start(_ id: UUID, name: String) async throws {
        try await transaction(CXStartCallAction(call: id, handle: CXHandle(type: .generic, value: name)))
        provider.reportCall(with: id, updated: update(name))
        provider.reportOutgoingCall(with: id, startedConnectingAt: nil)
    }
    func answer(_ id: UUID) async throws { try await transaction(CXAnswerCallAction(call: id)) }
    func end(_ id: UUID) async throws { try await transaction(CXEndCallAction(call: id)) }
    func mute(_ id: UUID, muted: Bool) async throws { try await transaction(CXSetMutedCallAction(call: id, muted: muted)) }
    func connected(_ id: UUID) { provider.reportOutgoingCall(with: id, connectedAt: Date()) }
    func ended(_ id: UUID, failed: Bool) { provider.reportCall(with: id, endedAt: Date(), reason: failed ? .failed : .remoteEnded) }

    private func transaction(_ action: CXAction) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            controller.request(CXTransaction(action: action)) { error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume() }
            }
        }
    }

    func providerDidReset(_ provider: CXProvider) { events?.systemReset() }
    func provider(_ provider: CXProvider, didActivate audioSession: AVAudioSession) { events?.systemAudioActivated() }
    func provider(_ provider: CXProvider, didDeactivate audioSession: AVAudioSession) { events?.systemAudioDeactivated() }
    func provider(_ provider: CXProvider, timedOutPerforming action: CXAction) {
        if let call = action as? CXCallAction { events?.systemActionTimedOut(call.callUUID) }
    }

    func provider(_ provider: CXProvider, perform action: CXStartCallAction) {
        Task { if await events?.systemStart(action.callUUID) == true { action.fulfill() } else { action.fail() } }
    }
    func provider(_ provider: CXProvider, perform action: CXAnswerCallAction) {
        Task { if await events?.systemAnswer(action.callUUID) == true { action.fulfill() } else { action.fail() } }
    }
    func provider(_ provider: CXProvider, perform action: CXEndCallAction) {
        Task { if await events?.systemEnd(action.callUUID) == true { action.fulfill() } else { action.fail() } }
    }
    func provider(_ provider: CXProvider, perform action: CXSetMutedCallAction) {
        Task { if await events?.systemMute(action.callUUID, muted: action.isMuted) == true { action.fulfill() } else { action.fail() } }
    }
}
