import Foundation

extension Notification.Name {
    static let familyRadioData = Notification.Name("org.meshchat.family.radio-data")
}

/// Coalesces an actual Bluetooth wake into a bounded inbox check, not a keep-alive.
@MainActor
final class FamilyRadioWake {
    typealias Expiration = @MainActor () -> Void
    private final class Run {
        let started: TimeInterval
        var lastPacket: TimeInterval
        var lease: Int?
        var task: Task<Void, Never>?
        var timeout: Task<Void, Never>?
        init(_ now: TimeInterval) { started = now; lastPacket = now }
    }

    private let begin: (@escaping Expiration) -> Int?
    private let end: (Int) -> Void
    private let now: () -> TimeInterval
    private let active: () -> Bool
    private let prepare: () async -> Void
    private let refresh: () async -> Void
    private let pause: () async throws -> Void
    private let timeout: () async throws -> Void
    private var run: Run?
    private var refreshing = false
    var isRunning: Bool { run != nil }

    init(begin: @escaping (@escaping Expiration) -> Int?, end: @escaping (Int) -> Void,
         now: @escaping () -> TimeInterval, active: @escaping () -> Bool,
         prepare: @escaping () async -> Void = {}, refresh: @escaping () async -> Void,
         pause: @escaping () async throws -> Void,
         timeout: @escaping () async throws -> Void = { try await Task.sleep(for: .seconds(15)) }) {
        self.begin = begin; self.end = end; self.now = now; self.active = active
        self.prepare = prepare; self.refresh = refresh; self.pause = pause; self.timeout = timeout
    }

    func received() {
        guard !active() else { return }
        if let run { run.lastPacket = now(); return }
        let value = Run(now())
        run = value
        let lease = begin { [weak self, weak value] in
            guard let self, let value else { return }
            self.finish(value)
        }
        // Expiration can win even before the lease callback returns.
        guard run === value else { if let lease { end(lease) }; return }
        guard let lease else { finish(value); return }
        value.lease = lease
        // Release the lease even if a permission or runtime request is suspended.
        value.timeout = Task { [weak self, weak value] in
            guard let self, let value else { return }
            do { try await self.timeout() } catch { return }
            self.finish(value)
        }
        value.task = Task { [weak self, weak value] in
            guard let self, let value else { return }
            defer { self.finish(value) }
            await self.prepare()
            while self.run === value && !Task.isCancelled && !self.active() && self.now() - value.started < 15 {
                // A cancelled await may still be finishing in the embedded runtime.
                // Do not queue overlapping status requests on a later radio wake.
                if !self.refreshing {
                    self.refreshing = true
                    await self.refresh()
                    self.refreshing = false
                }
                guard self.run === value, !Task.isCancelled, !self.active() else { break }
                // The Python radio reader may finish parsing after the first status read.
                if self.now() - value.started >= 3 && self.now() - value.lastPacket >= 2 { break }
                do { try await self.pause() } catch { break }
            }
        }
    }

    func stop() { if let run { finish(run) } }

    private func finish(_ value: Run) {
        guard run === value else { return }
        run = nil
        let task = value.task
        let timeout = value.timeout
        value.task = nil
        value.timeout = nil
        task?.cancel()
        timeout?.cancel()
        if let lease = value.lease { end(lease) }
    }
}
