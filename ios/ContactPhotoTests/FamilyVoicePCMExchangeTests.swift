import XCTest
@testable import FamilyLive

final class FamilyVoicePCMExchangeTests: XCTestCase {
    private let frame = FamilyVoicePCMExchange.frameBytes
    private let microphone = Data(repeating: 7, count: 1_920)

    func testReadyFramesReachThePlayerBeforePotentiallySlowEncoding() {
        var played: [Data] = []
        var operations: [String] = []
        let incoming = (1...3).reduce(into: Data()) { $0.append(Data(repeating: UInt8($1), count: frame)) }
        FamilyVoicePCMExchange.run(input: microphone, availableFrames: 3, exchange: { input, capacity in
            if input.isEmpty {
                operations.append("receive")
                XCTAssertEqual(capacity, self.frame * 3)
                return incoming
            }
            // This synchronous callback represents an encoder which can block.
            // All speaker buffers must already have been handed to the player.
            operations.append("encode")
            XCTAssertEqual(played.count, 3)
            XCTAssertEqual(input, self.microphone)
            XCTAssertEqual(capacity, 0)
            return Data()
        }, schedule: { played.append($0); operations.append("schedule"); return true })
        XCTAssertEqual(operations, ["receive", "schedule", "schedule", "schedule", "encode"])
        XCTAssertEqual(played, (1...3).map { Data(repeating: UInt8($0), count: frame) })
    }

    func testFullPlayerStillSendsCaptureOnceWithoutPullingAdditionalPCM() {
        var calls = 0
        FamilyVoicePCMExchange.run(input: microphone, availableFrames: 0, exchange: { input, capacity in
            calls += 1; XCTAssertEqual(input, self.microphone); XCTAssertEqual(capacity, 0)
            return Data()
        }, schedule: { _ in XCTFail("No playback capacity"); return false })
        XCTAssertEqual(calls, 1)
    }

    func testHardwareCompletionRefillsDoNotDuplicateMicrophoneCapture() {
        var calls = 0; var scheduled = 0
        FamilyVoicePCMExchange.run(input: Data(), availableFrames: 1, exchange: { input, capacity in
            calls += 1; XCTAssertTrue(input.isEmpty); XCTAssertEqual(capacity, self.frame)
            return Data(repeating: 1, count: self.frame)
        }, schedule: { _ in scheduled += 1; return true })
        XCTAssertEqual(calls, 1); XCTAssertEqual(scheduled, 1)
    }

    func testMissingOrMalformedPlaybackCannotSwallowValidCapture() {
        for size in [0, 1, 1_919, 1_921, 5_762] {
            var capture = 0
            FamilyVoicePCMExchange.run(input: microphone, availableFrames: 3, exchange: { input, _ in
                if input.isEmpty { return Data(repeating: 1, count: size) }
                capture += 1; XCTAssertEqual(input, self.microphone); return Data()
            }, schedule: { _ in XCTFail("Invalid PCM cannot be scheduled"); return false })
            XCTAssertEqual(capture, 1)
        }
    }

    func testTheExistingSixtyMillisecondLimitIsNotExpanded() {
        var played = 0
        FamilyVoicePCMExchange.run(input: Data(), availableFrames: 99, exchange: { _, capacity in
            XCTAssertEqual(capacity, self.frame * 3)
            return Data(repeating: 1, count: capacity)
        }, schedule: { _ in played += 1; return true })
        XCTAssertEqual(played, 3)
    }

    func testPlaybackSchedulingFailureStillSendsCaptureOnce() {
        var attempted = 0; var capture = 0
        FamilyVoicePCMExchange.run(input: microphone, availableFrames: 3, exchange: { input, capacity in
            if input.isEmpty { return Data(repeating: 1, count: capacity) }
            capture += 1; return Data()
        }, schedule: { _ in attempted += 1; return false })
        XCTAssertEqual(attempted, 1); XCTAssertEqual(capture, 1)
    }

    func testInvalidCaptureDoesNotReachTheBridgeOrStopPlayback() {
        for input in [Data(repeating: 1, count: 1), Data(repeating: 1, count: 11_522)] {
            var pulled = 0; var played = 0
            FamilyVoicePCMExchange.run(input: input, availableFrames: 1, exchange: { capture, capacity in
                XCTAssertTrue(capture.isEmpty); pulled += 1
                return Data(repeating: 1, count: capacity)
            }, schedule: { _ in played += 1; return true })
            XCTAssertEqual(pulled, 1); XCTAssertEqual(played, 1)
        }
    }
}
