// SPDX-License-Identifier: 0BSD
import Foundation
import XCTest

@MainActor private final class VoIPRegistryFixture: NextVoIPRegistryControlling {
    var identifier: ObjectIdentifier { ObjectIdentifier(self) }
    var listening: [Bool] = []
    func listen(_ enabled: Bool) { listening.append(enabled) }
}
@MainActor private final class VoIPCompletionFixture { var count = 0 }

@MainActor final class VoIPPushDeviceTests: XCTestCase {
    func testPersonalPreviewCannotCreateOrRegisterAVoIPRegistry() {
        XCTAssertFalse(["development", "production"].contains(Bundle.main.object(forInfoDictionaryKey: "NextPushEnvironment") as? String ?? ""))
        var created = 0
        let fake = VoIPRegistryFixture()
        let device = NextVoIPPushDevice(factory: { _ in created += 1; return fake },
            delivery: { _, _, _ in XCTFail("There is no enrolled registry") }, tokenChanged: { _ in })
        XCTAssertFalse(device.start()); XCTAssertFalse(device.active)
        XCTAssertEqual(created, 0); XCTAssertTrue(fake.listening.isEmpty)
    }
    func testExplicitEligibleRegistrationIsIdempotentAndStopsOnlyItsVoIPRegistry() {
        let fake = VoIPRegistryFixture()
        var created = 0, tokens: [Data?] = []
        let device = NextVoIPPushDevice(eligible: { true }, factory: { _ in created += 1; return fake },
            delivery: { _, _, _ in }, tokenChanged: { tokens.append($0) })
        XCTAssertTrue(device.start()); XCTAssertTrue(device.start())
        XCTAssertEqual(created, 1); XCTAssertEqual(fake.listening, [true])
        device.stop(); device.stop()
        XCTAssertFalse(device.active); XCTAssertEqual(fake.listening, [true, false])
        XCTAssertEqual(tokens.count, 1); XCTAssertNil(tokens.first!)
    }
    func testOnlyCurrentActiveRegistryMayPublishBoundedTokens() {
        let fake = VoIPRegistryFixture(), other = VoIPRegistryFixture()
        var tokens: [Data?] = []
        let device = NextVoIPPushDevice(eligible: { true }, factory: { _ in fake },
            delivery: { _, _, _ in }, tokenChanged: { tokens.append($0) })
        XCTAssertTrue(device.start())
        device.acceptToken(Data(repeating: 1, count: 32), from: other.identifier)
        XCTAssertTrue(tokens.isEmpty)
        let valid = Data(repeating: 2, count: 32)
        device.acceptToken(valid, from: fake.identifier)
        device.acceptToken(Data(repeating: 3, count: 257), from: fake.identifier)
        XCTAssertEqual(tokens.count, 2); XCTAssertEqual(tokens[0], valid); XCTAssertNil(tokens[1])
        device.stop(); let count = tokens.count
        device.acceptToken(valid, from: fake.identifier)
        XCTAssertEqual(tokens.count, count)
    }
    func testRequiredLateDeliverySurvivesStopAndCompletesExactlyOnce() {
        let fake = VoIPRegistryFixture(), counter = VoIPCompletionFixture()
        var received: Data?, required = false
        var callback: (@Sendable () -> Void)?
        let device = NextVoIPPushDevice(eligible: { true }, factory: { _ in fake },
            delivery: { data, mustReport, completion in received = data; required = mustReport; callback = completion }, tokenChanged: { _ in })
        XCTAssertTrue(device.start()); device.stop()
        let payload = Data("private fixture".utf8)
        device.acceptPayload(payload, mustReport: true) { MainActor.assumeIsolated { counter.count += 1 } }
        XCTAssertEqual(received, payload); XCTAssertTrue(required); XCTAssertEqual(counter.count, 0)
        callback?(); callback?()
        XCTAssertEqual(counter.count, 1); XCTAssertFalse(device.active)
    }
    func testOversizedPayloadStillReachesTheDispatcherWithItsOriginalOSRequirement() {
        let counter = VoIPCompletionFixture()
        var received: Data?, mustReport: Bool?
        let device = NextVoIPPushDevice(eligible: { false }, delivery: { data, required, completion in
            received = data; mustReport = required; completion()
        }, tokenChanged: { _ in })
        device.acceptPayload(Data(repeating: 1, count: 5121), mustReport: false) {
            MainActor.assumeIsolated { counter.count += 1 }
        }
        XCTAssertEqual(received, Data()); XCTAssertEqual(mustReport, false); XCTAssertEqual(counter.count, 1)
        XCTAssertFalse(device.active)
    }
}
