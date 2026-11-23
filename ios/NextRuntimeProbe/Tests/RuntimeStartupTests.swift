// SPDX-License-Identifier: 0BSD
import Foundation
import XCTest

@MainActor
private final class StartupEngine {
    var configurations: [Data?] = []
    var waiting: CheckedContinuation<NextRuntimeSession, Error>?
    var cancellationObserved = false
    func start(_ configuration: Data?) async throws -> NextRuntimeSession {
        configurations.append(configuration)
        let result: NextRuntimeSession = try await withCheckedThrowingContinuation { waiting = $0 }
        cancellationObserved = Task.isCancelled
        return result
    }
}

@MainActor
private final class WakeStartupDeadline {
    var waiting: CheckedContinuation<Void, Error>?
    var cancelled = false
    func pause() async throws {
        try Task.checkCancellation()
        try await withCheckedThrowingContinuation { waiting = $0 }
        cancelled = Task.isCancelled
    }
    func fire() { let continuation = waiting; waiting = nil; continuation?.resume() }
}

@MainActor
final class RuntimeStartupTests: XCTestCase {
    private var result: NextRuntimeSession {
        NextRuntimeSession(url: URL(string: "http://127.0.0.1:44242/#/messages")!, address: String(repeating: "a1", count: 16))
    }
    private func ready(_ check: () -> Bool) async throws {
        for _ in 0..<500 {
            if check() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("The private startup barrier was not reached")
        throw URLError(.timedOut)
    }

    func testConcurrentScreenAndWakeShareOneRuntimeAndSession() async throws {
        let engine = StartupEngine(), expected = result
        let startup = NextRuntimeStartup(start: engine.start)
        let scene = Task { try await startup.session(configuration: Data("screen".utf8)) }
        let wake = Task { try await startup.session(configuration: Data("wake".utf8)) }
        try await ready { engine.waiting != nil }
        XCTAssertEqual(engine.configurations.count, 1)
        engine.waiting?.resume(returning: expected)
        let sceneResult = try await scene.value, wakeResult = try await wake.value
        XCTAssertEqual(sceneResult, expected)
        XCTAssertEqual(wakeResult, expected)
        XCTAssertEqual(engine.configurations.count, 1)
    }

    func testCompletedStartupKeepsItsOriginAndDoesNotReplaceTheLiveConfiguration() async throws {
        var configurations: [Data?] = []
        let expected = result, initial = Data("saved peers".utf8)
        let startup = NextRuntimeStartup { configuration in
            configurations.append(configuration)
            return expected
        }
        let first = try await startup.session(configuration: initial)
        let later = try await startup.session(configuration: Data("different caller snapshot".utf8))
        XCTAssertEqual(first, later)
        XCTAssertEqual(later, expected)
        XCTAssertEqual(configurations.count, 1)
        XCTAssertEqual(configurations.first!, initial)
    }

    func testLeavingOneCallerCannotCancelTheRuntimeNeededByAnother() async throws {
        let engine = StartupEngine(), expected = result
        let startup = NextRuntimeStartup(start: engine.start)
        let leaving = Task { try await startup.session(configuration: nil) }
        try await ready { engine.waiting != nil }
        leaving.cancel()
        let remaining = Task { try await startup.session(configuration: nil) }
        engine.waiting?.resume(returning: expected)
        let leavingResult = try await leaving.value, remainingResult = try await remaining.value
        XCTAssertEqual(leavingResult, expected)
        XCTAssertEqual(remainingResult, expected)
        XCTAssertFalse(engine.cancellationObserved)
        XCTAssertEqual(engine.configurations.count, 1)
    }

    func testFailedInitializationCannotStartAPartiallyInitializedPythonAgain() async {
        enum Failed: Error { case startup }
        var calls = 0
        let startup = NextRuntimeStartup { _ in calls += 1; throw Failed.startup }
        for _ in 0..<2 {
            do { _ = try await startup.session(configuration: nil); XCTFail("Startup must fail") }
            catch Failed.startup { }
            catch { XCTFail("The original initialization error must be retained") }
        }
        XCTAssertEqual(calls, 1)
    }

    func testCallWakeDeadlineDoesNotWaitForOrCancelTheSharedInitialization() async throws {
        let engine = StartupEngine(), deadline = WakeStartupDeadline(), expected = result
        let startup = NextRuntimeStartup(start: engine.start, wakeDelay: deadline.pause)
        let wake = Task { try await startup.callWakeSession() }
        try await ready { engine.waiting != nil && deadline.waiting != nil }
        deadline.fire()
        do { _ = try await wake.value; XCTFail("A stalled wake must time out") }
        catch let error as URLError { XCTAssertEqual(error.code, .timedOut) }
        let screen = Task { try await startup.session(configuration: Data("must not replace saved settings".utf8)) }
        engine.waiting?.resume(returning: expected)
        let actual = try await screen.value
        XCTAssertEqual(actual, expected); XCTAssertEqual(engine.configurations.count, 1)
        XCTAssertNil(engine.configurations[0]); XCTAssertFalse(engine.cancellationObserved)
    }

    func testCancelledWakeReturnsBeforeInitializationAndDoesNotCancelTheScreen() async throws {
        let engine = StartupEngine(), deadline = WakeStartupDeadline(), expected = result
        let startup = NextRuntimeStartup(start: engine.start, wakeDelay: deadline.pause)
        let wake = Task { try await startup.callWakeSession() }
        try await ready { engine.waiting != nil && deadline.waiting != nil }
        wake.cancel()
        do { _ = try await wake.value; XCTFail("The removed wake must return cancellation") }
        catch is CancellationError { }
        deadline.fire()
        let screen = Task { try await startup.session(configuration: nil) }
        engine.waiting?.resume(returning: expected)
        let actual = try await screen.value
        XCTAssertEqual(actual, expected); XCTAssertFalse(engine.cancellationObserved)
        XCTAssertEqual(engine.configurations.count, 1)
    }

    func testReadyCallWakeCancelsOnlyItsDeadlineAndKeepsTheCachedSession() async throws {
        let engine = StartupEngine(), deadline = WakeStartupDeadline(), expected = result
        let startup = NextRuntimeStartup(start: engine.start, wakeDelay: deadline.pause)
        let wake = Task { try await startup.callWakeSession() }
        try await ready { engine.waiting != nil && deadline.waiting != nil }
        engine.waiting?.resume(returning: expected)
        let actual = try await wake.value
        XCTAssertEqual(actual, expected)
        deadline.fire()
        try await ready { deadline.cancelled }
        let cached = try await startup.callWakeSession()
        XCTAssertEqual(cached, expected); XCTAssertEqual(engine.configurations.count, 1)
        deadline.fire()
    }

    func testCallWakePropagatesTheRetainedStartupErrorWithoutRestartingPython() async throws {
        enum Failed: Error { case startup }
        var calls = 0
        let startup = NextRuntimeStartup { _ in calls += 1; throw Failed.startup }
        for _ in 0..<2 {
            do { _ = try await startup.callWakeSession(); XCTFail("The original failure must survive") }
            catch Failed.startup { }
        }
        XCTAssertEqual(calls, 1)
    }


    func testAlreadyCancelledWakeDoesNotInitializeAnyRuntime() async throws {
        var calls = 0
        let expected = result
        let startup = NextRuntimeStartup { _ in calls += 1; return expected }
        let wake = Task { try await startup.callWakeSession() }
        wake.cancel()
        do { _ = try await wake.value; XCTFail("A cancelled wake must not start Python") }
        catch is CancellationError { }
        XCTAssertEqual(calls, 0)
    }

}
