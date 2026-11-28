import XCTest
@testable import FamilyLive

final class FamilyVoicePlaybackClockTests: XCTestCase {
    func testNoWorkBeforeStartAndTheExistingSixtyMillisecondLimit() throws {
        var clock = FamilyVoicePlaybackClock()
        XCTAssertEqual(clock.available, 0)
        XCTAssertNil(clock.schedule())
        clock.start()
        for _ in 0..<3 { XCTAssertNotNil(clock.schedule()) }
        XCTAssertEqual(clock.scheduled, 3)
        XCTAssertEqual(clock.available, 0)
        XCTAssertNil(clock.schedule())
    }

    func testHardwareCompletionAllowsAnImmediateBoundedRefill() throws {
        var clock = FamilyVoicePlaybackClock(); clock.start()
        let first = try XCTUnwrap(clock.schedule())
        _ = try XCTUnwrap(clock.schedule()); _ = try XCTUnwrap(clock.schedule())
        XCTAssertTrue(clock.consumed(first))
        XCTAssertEqual(clock.available, 1)
        XCTAssertNotNil(clock.schedule())
        XCTAssertEqual(clock.scheduled, 3)
        XCTAssertNil(clock.schedule())
    }

    func testDuplicateAndUnknownCompletionsCannotReleaseAnotherBuffer() throws {
        var clock = FamilyVoicePlaybackClock(); clock.start()
        let first = try XCTUnwrap(clock.schedule())
        _ = try XCTUnwrap(clock.schedule())
        XCTAssertTrue(clock.consumed(first))
        XCTAssertFalse(clock.consumed(first))
        XCTAssertFalse(clock.consumed(999))
        XCTAssertEqual(clock.scheduled, 1)
    }

    func testStopRejectsQueuedCompletionsAndFurtherScheduling() throws {
        var clock = FamilyVoicePlaybackClock(); clock.start()
        let first = try XCTUnwrap(clock.schedule()); clock.stop()
        XCTAssertFalse(clock.consumed(first))
        XCTAssertEqual(clock.available, 0)
        XCTAssertNil(clock.schedule())
        XCTAssertEqual(clock.scheduled, 0)
    }

    func testACompletionFromThePreviousRunCannotConsumeANewLease() throws {
        var clock = FamilyVoicePlaybackClock(); clock.start()
        let previous = try XCTUnwrap(clock.schedule()); clock.stop(); clock.start()
        let current = try XCTUnwrap(clock.schedule())
        XCTAssertNotEqual(previous, current)
        XCTAssertFalse(clock.consumed(previous))
        XCTAssertEqual(clock.scheduled, 1)
        XCTAssertTrue(clock.consumed(current))
        XCTAssertEqual(clock.available, 3)
    }
}
