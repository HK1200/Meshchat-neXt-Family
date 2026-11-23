// SPDX-License-Identifier: 0BSD
import Foundation

struct NextRuntimeSession: Equatable, Sendable {
    let url: URL
    let address: String?
}

/// CPython and the Reticulum globals belong to one process-wide runtime.
/// A caller leaving the screen must not cancel or repeat its initialization.
@MainActor
final class NextRuntimeStartup {
    typealias Starter = @MainActor (Data?) async throws -> NextRuntimeSession
    typealias WakeDelay = @MainActor @Sendable () async throws -> Void
    private let start: Starter
    private var task: Task<NextRuntimeSession, Error>?
    private let wakeDelay: WakeDelay

    convenience init(start: @escaping Starter) {
        self.init(start: start, wakeDelay: { try await Task.sleep(for: .seconds(15)) })
    }
    init(start: @escaping Starter, wakeDelay: @escaping WakeDelay) {
        self.start = start; self.wakeDelay = wakeDelay
    }

    /// A call wake must release its completion promptly even when CPython is
    /// still starting. Never cancel the shared startup when this caller times
    /// out or loses permission. A later screen can still use the same runtime.
    func callWakeSession() async throws -> NextRuntimeSession {
        let waiter = WakeWaiter()
        let pause = wakeDelay
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                waiter.install(continuation)
                waiter.observer = Task { @MainActor in
                    do { waiter.finish(.success(try await self.session(configuration: nil))) }
                    catch { waiter.finish(.failure(error)) }
                }
                waiter.deadline = Task { @MainActor in
                    do {
                        try Task.checkCancellation()
                        try await pause()
                        try Task.checkCancellation()
                        waiter.finish(.failure(URLError(.timedOut)))
                    } catch { }
                }
            }
        } onCancel: {
            Task { @MainActor in waiter.finish(.failure(CancellationError())) }
        }
    }

    @MainActor
    private final class WakeWaiter {
        var observer: Task<Void, Never>?
        var deadline: Task<Void, Never>?
        private var continuation: CheckedContinuation<NextRuntimeSession, Error>?
        private var result: Result<NextRuntimeSession, Error>?
        func install(_ continuation: CheckedContinuation<NextRuntimeSession, Error>) {
            if let result { continuation.resume(with: result) }
            else { self.continuation = continuation }
        }
        func finish(_ result: Result<NextRuntimeSession, Error>) {
            guard self.result == nil else { return }
            self.result = result
            let continuation = self.continuation; self.continuation = nil
            observer?.cancel(); observer = nil
            deadline?.cancel(); deadline = nil
            continuation?.resume(with: result)
        }
    }

    func session(configuration: Data?) async throws -> NextRuntimeSession {
        if let task { return try await task.value }
        let start = self.start
        let task = Task { @MainActor in try await start(configuration) }
        self.task = task
        // Retain successes and failures. CPython may already be partially
        // initialized after an error; starting it again in this process is
        // unsafe. Ordinary peer edits still use the running settings API.
        return try await task.value
    }
}
