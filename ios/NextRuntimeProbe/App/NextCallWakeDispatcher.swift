// SPDX-License-Identifier: 0BSD
import Foundation

/// Delivery contract for a future explicitly enrolled PushKit registry. This
/// object does not register for pushes or opt a user into any provider.
@MainActor
final class NextCallWakeDispatcher {
    typealias Context = @MainActor () -> NextCallWakeContext?
    typealias CancellationCheck = @MainActor (FamilyCallWake, NextCallWakeContext) async -> Bool
    typealias PollDelay = @MainActor @Sendable () async throws -> Void
    private let system: FamilySystemCalls
    private let router: NextReticulumWakeRouter
    private let runtime: NextRuntimeStartup
    private let context: Context
    private var boots: [UUID: Task<Void, Never>] = [:]
    private var cancellationPolls: [UUID: Task<Void, Never>] = [:]
    private let cancellationCheck: CancellationCheck?
    private let pollDelay: PollDelay

    init(system: FamilySystemCalls, router: NextReticulumWakeRouter,
         runtime: NextRuntimeStartup, context: @escaping Context,
         cancellationCheck: CancellationCheck? = nil,
         pollDelay: @escaping PollDelay = { try await Task.sleep(for: .seconds(2)) }) {
        self.system = system; self.router = router; self.runtime = runtime; self.context = context
        self.cancellationCheck = cancellationCheck; self.pollDelay = pollDelay
    }

    /// mustReport comes from the OS metadata, never an untrusted payload.
    /// Completion follows the actual CallKit callback, not CPython startup.
    func receive(_ payload: Data, mustReport: Bool,
                 completion: @escaping @MainActor () -> Void) {
        let finished = Completion(completion)
        guard let saved = context() else { reject(mustReport, finished); return }
        let decision = router.accept(payload, recipientPrivateKey: saved.recipientPrivateKey,
            recipientPublicKey: saved.recipientPublicKey, audience: saved.audience,
            approvedNames: saved.approvedNames, permitted: { [weak self] in
                self?.context() == saved
            })
        guard case .accepted(let id) = decision else {
            reject(mustReport, finished)
            return
        }
        if let cancellationCheck, let intent = router.pendingIntent(id) {
            let pause = pollDelay
            cancellationPolls[id] = Task { @MainActor [weak self, router] in
                defer { self?.cancellationPolls.removeValue(forKey: id) }
                // Never poll after expiry, consent loss or transport adoption.
                for _ in 0..<15 {
                    guard !Task.isCancelled, self?.context() == saved,
                          router.pendingIntent(id) == intent else { return }
                    let cancelled = await cancellationCheck(intent, saved)
                    guard !Task.isCancelled, self?.context() == saved,
                          router.pendingIntent(id) == intent else { return }
                    if cancelled { router.cancel(id); return }
                    do { try await pause() } catch { return }
                }
            }
        }
        // Reporting is already queued by admission. Start signaling in
        // parallel, without keeping the PushKit completion open for startup.
        boots[id] = Task { @MainActor [weak self, runtime, router] in
            defer { self?.boots.removeValue(forKey: id) }
            do {
                _ = try await runtime.callWakeSession()
                router.refresh()
            } catch { router.cancel(id) }
        }
        Task { @MainActor [system, router] in
            if !(await system.incomingAttemptCompleted(id)) { router.cancel(id) }
            finished.finish()
        }
    }

    func refreshConsent() { router.refresh() }

    func stop() {
        router.close()
        let pending = Array(boots.values) + Array(cancellationPolls.values)
        boots.removeAll(); cancellationPolls.removeAll()
        for task in pending { task.cancel() }
    }

    private func reject(_ mustReport: Bool, _ finished: Completion) {
        guard mustReport else { finished.finish(); return }
        Task { @MainActor [system] in
            await system.reportUnusableWake()
            finished.finish()
        }
    }

    @MainActor
    private final class Completion {
        private var action: (@MainActor () -> Void)?
        init(_ action: @escaping @MainActor () -> Void) { self.action = action }
        func finish() { let callback = action; action = nil; callback?() }
    }
}
