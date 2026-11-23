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
    private let start: Starter
    private var task: Task<NextRuntimeSession, Error>?

    init(start: @escaping Starter) { self.start = start }

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
