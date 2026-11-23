import XCTest

private final class SIPCallDriver: NextSIPDriving {
    var commands: [(Int32, String?, String)] = []
    var stops = 0
    var accepted = true
    func start(_ account: NextSIPAccountValues, events: @escaping NextSIPEventSink, closed: @escaping NextSIPExitSink) -> Bool { true }
    func command(_ operation: Int32, value: String?, callID: String) -> Bool {
        commands.append((operation, value, callID)); return accepted
    }
    func stop() { stops += 1 }
}
@MainActor
private final class SIPCallAudio: NextSIPCallAudio {
    var allowed = true
    var preparations = 0
    var ended = 0
    var outputs: [Bool] = []
    var waiting: CheckedContinuation<Bool, Never>?
    var suspend = false
    func prepare(managed: Bool) async -> Bool {
        preparations += 1
        if suspend { return await withCheckedContinuation { waiting = $0 } }
        return allowed
    }
    func speaker(_ enabled: Bool) -> Bool { outputs.append(enabled); return true }
    func finish(managed: Bool) { ended += 1 }
}
@MainActor
private final class SIPCallSystemDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    var starts: [UUID] = []; var incomingCalls: [UUID] = []; var ends: [UUID] = []
    func incoming(_ id: UUID, name: String) async throws { incomingCalls.append(id) }
    func start(_ id: UUID, name: String) async throws { starts.append(id) }
    func answer(_ id: UUID) async throws { _ = await events?.systemAnswer(id) }
    func end(_ id: UUID) async throws { _ = await events?.systemEnd(id) }
    func mute(_ id: UUID, muted: Bool) async throws { _ = await events?.systemMute(id, muted: muted) }
    func connected(_ id: UUID) {}
    func ended(_ id: UUID, failed: Bool) { ends.append(id) }
}

@MainActor
private final class SIPTestWakeRouter: NextIncomingCallWakeRouting {
    let peer: String
    let pending: FamilySystemCallKey
    var adoptions: [(FamilySystemCallKey, FamilySystemCallKey)] = []
    init(peer: String, pending: FamilySystemCallKey) { self.peer = peer; self.pending = pending }
    func pendingIncoming(peer: String, service: FamilySystemCallKey.Service) -> FamilySystemCallKey? {
        peer == self.peer && service == pending.service ? pending : nil
    }
    func attached(_ pending: FamilySystemCallKey, to key: FamilySystemCallKey) { adoptions.append((pending, key)) }
}

final class SIPCallSessionTests: XCTestCase {
    @MainActor
    private func settle() async { for _ in 0..<20 { await Task.yield() } }

    @MainActor
    func testDialMicrophoneAndSystemAudioMustCompleteBeforeNativeStart() async throws {
        let driver = SIPCallDriver(), audio = SIPCallAudio(), systemDriver = SIPCallSystemDriver()
        let system = FamilySystemCalls(driver: systemDriver, preferences: nil, enabled: true)
        var events: [[String: Any]] = []
        let call = NextSIPCallSession(driver: driver, system: system, audio: audio, observeAudio: false) { events.append($0) }
        XCTAssertTrue(call.perform(["op":"dial","call_id":"outgoing","peer":"sip:9002@127.0.0.1:55162"]))
        await settle()
        let id = try XCTUnwrap(systemDriver.starts.first)
        XCTAssertTrue(driver.commands.isEmpty)
        let started = await system.systemStart(id)
        XCTAssertTrue(started)
        XCTAssertEqual(audio.preparations, 1)
        XCTAssertTrue(driver.commands.isEmpty)
        system.systemAudioActivated(); await settle()
        XCTAssertEqual(driver.commands.first?.0, 1)
        XCTAssertEqual(driver.commands.first?.2, "outgoing")
        call.receive("connected", peer: "ignored", code: 0, id: "outgoing")
        XCTAssertTrue(call.perform(["op":"mute","call_id":"outgoing","value":true]))
        await settle()
        XCTAssertEqual(driver.commands.last?.0, 4)
        XCTAssertEqual(driver.commands.last?.1, "1")
        XCTAssertTrue(call.perform(["op":"hangup","call_id":"outgoing"]))
        await settle()
        XCTAssertEqual(driver.commands.last?.0, 3)
        XCTAssertFalse(system.hasCall)
        XCTAssertEqual(events.last?["state"] as? String, "ended")
        call.close()
    }

    @MainActor
    func testIncomingAnswerAndRemoteEndStayBoundToTheCurrentCall() async throws {
        let driver = SIPCallDriver(), audio = SIPCallAudio(), systemDriver = SIPCallSystemDriver()
        let system = FamilySystemCalls(driver: systemDriver, preferences: nil, enabled: true)
        var events: [[String: Any]] = []
        let call = NextSIPCallSession(driver: driver, system: system, audio: audio, observeAudio: false) { events.append($0) }
        call.receive("incoming", peer:"sip:9002@127.0.0.1:55162", code:0, id:"incoming")
        call.receive("incoming", peer:"sip:9002@127.0.0.1:55162", code:0, id:"incoming")
        await settle()
        XCTAssertEqual(systemDriver.incomingCalls.count, 1)
        XCTAssertTrue(driver.commands.isEmpty)
        let id = try XCTUnwrap(systemDriver.incomingCalls.first)
        let answered = await system.systemAnswer(id)
        XCTAssertTrue(answered)
        XCTAssertTrue(driver.commands.isEmpty)
        system.systemAudioActivated(); await settle()
        XCTAssertEqual(driver.commands.first?.0, 2)
        call.receive("connected", peer:"", code:0, id:"incoming")
        call.receive("ended", peer:"", code:0, id:"wrong-call")
        XCTAssertTrue(system.hasCall)
        call.receive("ended", peer:"", code:0, id:"incoming")
        XCTAssertFalse(system.hasCall)
        let count = events.count
        call.receive("incoming", peer:"sip:9002@127.0.0.1:55162", code:0, id:"incoming")
        call.receive("connected", peer:"", code:0, id:"incoming")
        XCTAssertEqual(events.count, count)
        XCTAssertFalse(call.perform(["op":"answer","call_id":"incoming"]))
        call.close()
    }

    @MainActor
    func testDeniedMicrophoneEndsWithoutDialing() async {
        let driver = SIPCallDriver(), audio = SIPCallAudio(); audio.allowed = false
        let system = FamilySystemCalls(driver: SIPCallSystemDriver(), preferences:nil, enabled:false)
        var events: [[String: Any]] = []
        let call = NextSIPCallSession(driver:driver, system:system, audio:audio, observeAudio:false) { events.append($0) }
        XCTAssertTrue(call.perform(["op":"dial","call_id":"denied","peer":"sip:9002@127.0.0.1"]))
        await settle()
        XCTAssertTrue(driver.commands.isEmpty)
        XCTAssertEqual(events.last?["state"] as? String, "ended")
        call.close()
    }

    @MainActor
    func testClosingDuringMicrophonePermissionCannotStartTheOldCall() async {
        let driver = SIPCallDriver(), audio = SIPCallAudio(); audio.suspend = true
        let system = FamilySystemCalls(driver:SIPCallSystemDriver(), preferences:nil, enabled:false)
        let call = NextSIPCallSession(driver:driver, system:system, audio:audio, observeAudio:false) { _ in }
        XCTAssertTrue(call.perform(["op":"dial","call_id":"pending","peer":"sip:9002@127.0.0.1"]))
        await settle(); XCTAssertNotNil(audio.waiting)
        call.close(); audio.waiting?.resume(returning:true); audio.waiting = nil
        await settle()
        XCTAssertTrue(driver.commands.isEmpty)
        XCTAssertFalse(call.perform(["op":"dial","call_id":"later","peer":"sip:9002@127.0.0.1"]))
    }

    @MainActor
    func testBusyMalformedAndStaleControlsCannotReachAnotherCall() async {
        let driver = SIPCallDriver(), audio = SIPCallAudio()
        let system = FamilySystemCalls(driver:SIPCallSystemDriver(), preferences:nil, enabled:false)
        let call = NextSIPCallSession(driver:driver, system:system, audio:audio, observeAudio:false) { _ in }
        call.receive("incoming", peer:"sip:9002@127.0.0.1", code:0, id:"one")
        call.receive("incoming", peer:"sip:9003@127.0.0.1", code:0, id:"two")
        XCTAssertEqual(driver.commands.last?.0, 3)
        XCTAssertEqual(driver.commands.last?.2, "two")
        let count = driver.commands.count
        XCTAssertFalse(call.perform(["op":"answer","call_id":"other"]))
        XCTAssertFalse(call.perform(["op":"mute","call_id":"one","value":1]))
        XCTAssertFalse(call.perform(["op":"digit","call_id":"one","digit":"12"]))
        XCTAssertEqual(driver.commands.count, count)
        call.receive("connected", peer:"", code:0, id:"one")
        XCTAssertTrue(call.perform(["op":"digit","call_id":"one","digit":"5"]))
        XCTAssertEqual(driver.commands.last?.0, 5)
        XCTAssertEqual(driver.commands.last?.1, "5")
        XCTAssertTrue(call.perform(["op":"hold","call_id":"one","value":true]))
        XCTAssertEqual(driver.commands.last?.0, 6)
        XCTAssertEqual(driver.commands.last?.1, "1")
        call.close()
    }

    @MainActor
    func testFailedNativeHangupStopsTheEngineInsteadOfLeavingAudioRunning() {
        let driver = SIPCallDriver(), audio = SIPCallAudio()
        let system = FamilySystemCalls(driver:SIPCallSystemDriver(), preferences:nil, enabled:false)
        let call = NextSIPCallSession(driver:driver, system:system, audio:audio, observeAudio:false) { _ in }
        call.receive("incoming", peer:"sip:9002@127.0.0.1", code:0, id:"one")
        driver.accepted = false
        XCTAssertTrue(call.perform(["op":"hangup","call_id":"one"]))
        XCTAssertEqual(driver.stops, 1)
        XCTAssertEqual(audio.ended, 1)
        call.close(); XCTAssertEqual(audio.ended, 1)
    }
    @MainActor
    func testReticulumCallsUseStrictAddressesAndStartNativeAudioAfterConnection() async {
        let driver = SIPCallDriver(), audio = SIPCallAudio()
        let system = FamilySystemCalls(driver: SIPCallSystemDriver(), preferences: nil, enabled: false)
        let call = NextSIPCallSession(driver: driver, system: system, audio: audio, observeAudio: false,
            service: .reticulum,
            normalizePeer: { $0.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil ? $0.lowercased() : nil },
            displayName: { _ in "Saved contact" }, emit: { _ in })
        let id = String(repeating: "a", count: 32), peer = String(repeating: "b", count: 32)
        XCTAssertFalse(call.perform(["op":"dial","call_id":id,"peer":"sip:9002@127.0.0.1"]))
        XCTAssertTrue(call.perform(["op":"dial","call_id":id,"peer":peer]))
        await settle()
        XCTAssertEqual(driver.commands.map { $0.0 }, [1])
        call.receive("connected", peer: peer, code: 0, id: id)
        XCTAssertTrue(driver.commands.contains { $0.0 == 7 && $0.2 == id })
        XCTAssertFalse(call.perform(["op":"speaker","call_id":String(repeating: "c", count: 32),"value":true]))
        XCTAssertTrue(audio.outputs.isEmpty)
        XCTAssertTrue(call.perform(["op":"speaker","call_id":id,"value":true]))
        XCTAssertTrue(call.perform(["op":"speaker","call_id":id,"value":false]))
        XCTAssertEqual(audio.outputs, [true, false])
        XCTAssertFalse(call.perform(["op":"hangup","call_id":String(repeating: "c", count: 32)]))
        XCTAssertTrue(call.hasActiveCall)
        call.receive("ended", peer: peer, code: 0, id: id)
        XCTAssertFalse(call.hasActiveCall)
        call.close()
    }

    @MainActor
    func testReticulumCannotTakeOverAnActiveSIPSystemCall() async {
        let system = FamilySystemCalls(driver: SIPCallSystemDriver(), preferences: nil, enabled: true)
        let sipDriver = SIPCallDriver(), rnsDriver = SIPCallDriver()
        let sip = NextSIPCallSession(driver: sipDriver, system: system, audio: SIPCallAudio(), observeAudio: false, emit: { _ in })
        let rns = NextSIPCallSession(driver: rnsDriver, system: system, audio: SIPCallAudio(), observeAudio: false,
            service: .reticulum,
            normalizePeer: { $0.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil ? $0 : nil }, emit: { _ in })
        XCTAssertTrue(sip.perform(["op":"dial","call_id":"sip-owner","peer":"sip:9002@127.0.0.1"]))
        rns.receive("incoming", peer: String(repeating: "b", count: 32), code: 0, id: String(repeating: "a", count: 32))
        XCTAssertTrue(sip.hasActiveCall)
        XCTAssertFalse(rns.hasActiveCall)
        XCTAssertEqual(rnsDriver.commands.map { $0.0 }, [3])
        XCTAssertFalse(sipDriver.commands.contains { $0.0 == 3 })
        sip.close(); rns.close()
    }

    @MainActor
    func testAuthenticatedTransportAdoptsReservedWakeAndCompletesItsEarlyAnswerOnce() async throws {
        let driver = SIPCallDriver(), audio = SIPCallAudio(), systemDriver = SIPCallSystemDriver()
        let system = FamilySystemCalls(driver: systemDriver, preferences: nil, enabled: true)
        let peer = String(repeating: "a1", count: 16)
        let pending = FamilySystemCallKey(service: .reticulum, id: "private-pending-wake")
        let id = UUID()
        let placeholder = FamilySystemCallActions(prepareAudio: { XCTFail("Do not prepare before the real transport"); return false },
            start: { false }, answer: { XCTFail("Do not answer a placeholder"); return false }, end: {}, mute: { _ in false })
        XCTAssertTrue(system.reserveIncoming(pending, id: id, name: "Approved caller", actions: placeholder))
        let router = SIPTestWakeRouter(peer: peer, pending: pending)
        let call = NextSIPCallSession(driver: driver, system: system, audio: audio, observeAudio: false,
            service: .reticulum, normalizePeer: { $0 }, wakeRouter: router) { _ in }
        var completed: Bool?
        let answering = Task { let result = await system.systemAnswer(id); completed = result; return result }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNil(completed); XCTAssertEqual(audio.preparations, 0); XCTAssertTrue(driver.commands.isEmpty)
        call.receive("incoming", peer: peer, code: 0, id: "private-arrived-transport")
        let accepted = await answering.value
        XCTAssertTrue(accepted)
        system.systemAudioActivated(); await settle()
        XCTAssertEqual(audio.preparations, 1)
        XCTAssertEqual(driver.commands.filter { $0.0 == 2 }.count, 1)
        XCTAssertEqual(router.adoptions.count, 1)
        XCTAssertFalse(system.contains(pending))
        XCTAssertTrue(system.contains(FamilySystemCallKey(service: .reticulum, id: "private-arrived-transport")))
        XCTAssertEqual(systemDriver.incomingCalls, [id])
        call.receive("incoming", peer: peer, code: 0, id: "private-arrived-transport")
        await settle()
        XCTAssertEqual(router.adoptions.count, 1); XCTAssertEqual(systemDriver.incomingCalls, [id])
        XCTAssertTrue(call.perform(["op": "hangup", "call_id": "private-arrived-transport"]))
        await settle(); XCTAssertFalse(system.hasCall); call.close()
    }

    @MainActor
    func testOtherIncomingPeerCannotTakeOverAnApprovedReservedWake() async throws {
        let driver = SIPCallDriver(), audio = SIPCallAudio(), systemDriver = SIPCallSystemDriver()
        let system = FamilySystemCalls(driver: systemDriver, preferences: nil, enabled: true)
        let peer = String(repeating: "a1", count: 16), other = String(repeating: "b2", count: 16)
        let pending = FamilySystemCallKey(service: .reticulum, id: "private-approved-wake")
        let id = UUID()
        XCTAssertTrue(system.reserveIncoming(pending, id: id, name: "Approved caller",
            actions: FamilySystemCallActions(prepareAudio: { false }, start: { false }, answer: { false }, end: {}, mute: { _ in false })))
        let router = SIPTestWakeRouter(peer: peer, pending: pending)
        let call = NextSIPCallSession(driver: driver, system: system, audio: audio, observeAudio: false,
            service: .reticulum, normalizePeer: { $0 }, wakeRouter: router) { _ in }
        call.receive("incoming", peer: other, code: 0, id: "private-other-transport")
        XCTAssertFalse(call.hasActiveCall); XCTAssertTrue(system.contains(pending)); XCTAssertTrue(router.adoptions.isEmpty)
        XCTAssertEqual(driver.commands.last?.0, 3); XCTAssertEqual(driver.commands.last?.2, "private-other-transport")
        call.receive("incoming", peer: peer, code: 0, id: "private-approved-transport")
        await settle()
        XCTAssertTrue(call.hasActiveCall); XCTAssertEqual(router.adoptions.count, 1)
        XCTAssertEqual(systemDriver.incomingCalls, [id])
        call.close(); await settle(); XCTAssertFalse(system.hasCall)
    }

}
