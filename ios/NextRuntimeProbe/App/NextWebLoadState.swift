import Foundation
import Combine

/// A native fallback remains usable if WebKit cannot provide its remote tree.
@MainActor
final class NextWebLoadState: ObservableObject {
    static let pageReadyScript = "return document.readyState === 'complete' && (document.getElementById('app')?.childElementCount ?? 0) > 0;"
    @Published private(set) var loading = true
    @Published private(set) var problem: String?
    @Published private(set) var retryRequest = 0
    private(set) var generation = 0
    private var rendererRetryUsed = false

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
        rendererRetryUsed = false
    }

    func failed(_ expected: Int) {
        guard expected == generation else { return }
        loading = false
        problem = "The interface could not load. Your saved conversations and connections are still available."
    }

    func rendererTerminated() -> Bool {
        guard !rendererRetryUsed else { failed(generation); return false }
        rendererRetryUsed = true
        return true
    }

    func retry() {
        rendererRetryUsed = false
        retryRequest += 1
    }
}
