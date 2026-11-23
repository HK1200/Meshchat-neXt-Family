// SPDX-License-Identifier: 0BSD
import Foundation
@preconcurrency import PushKit

@MainActor
protocol NextVoIPRegistryControlling: AnyObject {
    var identifier: ObjectIdentifier { get }
    func listen(_ enabled: Bool)
}

@MainActor
private final class NextAppleVoIPRegistry: NextVoIPRegistryControlling {
    let registry: PKPushRegistry
    init(delegate: any PKPushRegistryDelegate) {
        registry = PKPushRegistry(queue: .main)
        registry.delegate = delegate
    }
    var identifier: ObjectIdentifier { ObjectIdentifier(registry) }
    func listen(_ enabled: Bool) { registry.desiredPushTypes = enabled ? [.voIP] : [] }
}

/// Owns only the VoIP registration. It never changes UIApplication's ordinary
/// message-push registration, notification preferences or background modes.
/// A personal-signing preview is ineligible even when a caller asks to start.
@MainActor
final class NextVoIPPushDevice: NSObject, PKPushRegistryDelegate {
    typealias Delivery = @MainActor (Data, Bool, @escaping @Sendable () -> Void) -> Void
    typealias RegistryFactory = @MainActor (any PKPushRegistryDelegate) -> any NextVoIPRegistryControlling
    private let eligible: @MainActor () -> Bool
    private let factory: RegistryFactory
    private let delivery: Delivery
    private let tokenChanged: @MainActor (Data?) -> Void
    private var registry: (any NextVoIPRegistryControlling)?
    private(set) var active = false

    init(eligible: @escaping @MainActor () -> Bool = {
        let value = Bundle.main.object(forInfoDictionaryKey: "NextPushEnvironment") as? String
        return value == "development" || value == "production"
    }, factory: RegistryFactory? = nil, delivery: @escaping Delivery,
         tokenChanged: @escaping @MainActor (Data?) -> Void) {
        self.eligible = eligible
        self.factory = factory ?? { NextAppleVoIPRegistry(delegate: $0) }
        self.delivery = delivery; self.tokenChanged = tokenChanged
        super.init()
    }

    @discardableResult
    func start() -> Bool {
        guard eligible() else { stop(); return false }
        if active { return true }
        if registry == nil { registry = factory(self) }
        active = true
        registry?.listen(true)
        return true
    }

    func stop() {
        guard active else { return }
        active = false
        registry?.listen(false)
        tokenChanged(nil)
        // Keep the delegate alive for already queued OS deliveries. Required
        // late pushes still reach dispatch and its revoked-consent path.
    }

    func acceptToken(_ token: Data?, from identifier: ObjectIdentifier) {
        guard active, registry?.identifier == identifier else { return }
        guard let token, (16...256).contains(token.count) else { tokenChanged(nil); return }
        tokenChanged(token)
    }

    func acceptPayload(_ data: Data, mustReport: Bool,
                       completion: @escaping @Sendable () -> Void) {
        // Do not discard a required push merely because registration stopped
        // after the OS queued it. The dispatcher checks consent independently.
        let once = CompletionOnce(completion)
        delivery(data.count <= 5120 ? data : Data(), mustReport) {
            if Thread.isMainThread { MainActor.assumeIsolated { once.finish() } }
            else { Task { @MainActor in once.finish() } }
        }
    }

    @MainActor
    private final class CompletionOnce {
        private var action: (@Sendable () -> Void)?
        init(_ action: @escaping @Sendable () -> Void) { self.action = action }
        func finish() { let callback = action; action = nil; callback?() }
    }

    private nonisolated func onMain(_ action: @escaping @MainActor @Sendable () -> Void) {
        // The owned registry explicitly uses the main queue. Retain a fallback
        // for a platform callback delivered on another queue.
        if Thread.isMainThread { MainActor.assumeIsolated { action() } }
        else { Task { @MainActor in action() } }
    }

    nonisolated func pushRegistry(_ registry: PKPushRegistry,
                                 didUpdate pushCredentials: PKPushCredentials, for type: PKPushType) {
        guard type == .voIP else { return }
        let identifier = ObjectIdentifier(registry), token = pushCredentials.token
        onMain { [self] in acceptToken(token, from: identifier) }
    }
    nonisolated func pushRegistry(_ registry: PKPushRegistry, didInvalidatePushTokenFor type: PKPushType) {
        guard type == .voIP else { return }
        let identifier = ObjectIdentifier(registry)
        onMain { [self] in acceptToken(nil, from: identifier) }
    }
    nonisolated func pushRegistry(_ registry: PKPushRegistry, didReceiveIncomingPushWith payload: PKPushPayload,
                                 for type: PKPushType, completion: @escaping @Sendable () -> Void) {
        guard type == .voIP else { completion(); return }
        let data = Self.encode(payload.dictionaryPayload)
        onMain { [self] in acceptPayload(data, mustReport: true, completion: completion) }
    }
    @available(iOS 26.4, *)
    nonisolated func pushRegistry(_ registry: PKPushRegistry, didReceiveIncomingVoIPPushWith payload: PKPushPayload,
                                 metadata: PKVoIPPushMetadata, withCompletionHandler completion: @escaping @Sendable () -> Void) {
        let data = Self.encode(payload.dictionaryPayload), mustReport = metadata.mustReport
        onMain { [self] in acceptPayload(data, mustReport: mustReport, completion: completion) }
    }
    private nonisolated static func encode(_ payload: [AnyHashable: Any]) -> Data {
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload), data.count <= 5120 else { return Data() }
        return data
    }
}
