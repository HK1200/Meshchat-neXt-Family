import XCTest

@MainActor
final class WebLoadStateTests: XCTestCase {
    func testFailureStaysVisibleUntilTheMatchingNavigationFinishes() {
        let state = NextWebLoadState()
        let first = state.begin()
        XCTAssertTrue(state.loading)
        state.failed(first)
        XCTAssertFalse(state.loading)
        XCTAssertNotNil(state.problem)
        let next = state.begin()
        state.ready(first)
        XCTAssertTrue(state.loading)
        state.failed(first)
        XCTAssertNil(state.problem)
        state.ready(next)
        XCTAssertFalse(state.loading)
        XCTAssertNil(state.problem)
    }

    func testRendererRecoveryIsBoundedUntilSuccessOrAnExplicitRetry() {
        let state = NextWebLoadState()
        _ = state.begin()
        XCTAssertTrue(state.rendererTerminated())
        _ = state.begin()
        XCTAssertFalse(state.rendererTerminated())
        XCTAssertNotNil(state.problem)
        XCTAssertEqual(state.retryRequest, 0)
        state.retry()
        XCTAssertEqual(state.retryRequest, 1)
        XCTAssertTrue(state.rendererTerminated())
        state.ready(state.begin())
        XCTAssertTrue(state.rendererTerminated())
    }

    func testAnOldWatchdogCannotReplaceANewerReadyPage() {
        let state = NextWebLoadState()
        let old = state.begin()
        let current = state.begin()
        state.ready(current)
        state.failed(old)
        XCTAssertFalse(state.loading)
        XCTAssertNil(state.problem)
    }
}
