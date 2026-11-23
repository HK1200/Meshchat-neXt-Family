// SPDX-License-Identifier: 0BSD
import Foundation

/// neXt's process-wide runtime adapter. Family supplies its own single model
/// through the shared dispatcher's closure; neither app initializes the other.
@MainActor extension NextCallWakeDispatcher {
    convenience init(system: FamilySystemCalls, router: NextReticulumWakeRouter,
                     runtime: NextRuntimeStartup, context: @escaping Context,
                     admitted: @escaping Admission = { _, _ in true },
                     cancellationCheck: CancellationCheck? = nil,
                     pollDelay: @escaping PollDelay = { try await Task.sleep(for: .seconds(2)) }) {
        self.init(system: system, router: router,
            startRuntime: { _ = try await runtime.callWakeSession() },
            context: context, admitted: admitted,
            cancellationCheck: cancellationCheck, pollDelay: pollDelay)
    }
}
