import Foundation
import Combine

/// A native fallback remains usable if WebKit cannot provide its remote tree.
@MainActor
final class NextWebLoadState: ObservableObject {
    static let pageReadyScript = """
        const splash = document.getElementById('meshchatnext-boot-splash');
        const style = splash ? getComputedStyle(splash) : null;
        const splashVisible = splash && !splash.hidden && splash.getClientRects().length > 0
            && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0;
        return document.readyState === 'complete'
            && (document.getElementById('app')?.childElementCount ?? 0) > 0 && !splashVisible;
        """
    @Published private(set) var loading = true
    @Published private(set) var problem: String?
    @Published private(set) var retryRequest = 0
    private(set) var generation = 0
    private var automaticRetryUsed = false

    var accessibilityValue: String {
        if loading { return "Loading interface" }
        return problem == nil ? "Interface ready" : "Interface unavailable"
    }

    /// A stalled boot and a renderer crash share one automatic recovery budget.
    func startupStalled(_ expected: Int) -> Bool {
        guard expected == generation, loading else { return false }
        guard !automaticRetryUsed else { failed(expected); return false }
        automaticRetryUsed = true
        return true
    }

    @discardableResult
    func begin() -> Int {
        generation += 1
        loading = true
        problem = nil
        return generation
    }

    func ready(_ expected: Int) {
        guard expected == generation else { return }
        loading = false
        problem = nil
        automaticRetryUsed = false
    }

    func failed(_ expected: Int) {
        guard expected == generation else { return }
        loading = false
        problem = "The interface could not load. Your saved conversations and connections are still available."
    }

    func rendererTerminated() -> Bool {
        guard !automaticRetryUsed else { failed(generation); return false }
        automaticRetryUsed = true
        return true
    }

    func retry() {
        automaticRetryUsed = false
        retryRequest += 1
    }
}
