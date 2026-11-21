import XCTest

private final class FakeNextSIPDriver: NextSIPDriving {
    var accounts: [NextSIPAccountValues] = []
    var events: NextSIPEventSink?
    var exit: NextSIPExitSink?
    var stops = 0
    var rejections: [String] = []
    func start(_ account: NextSIPAccountValues, events: @escaping NextSIPEventSink, closed: @escaping NextSIPExitSink) -> Bool {
        accounts.append(account); self.events = events; exit = closed; return true
    }
    func command(_ operation: Int32, value: String?, callID: String) -> Bool { XCTAssertEqual(operation, 3); rejections.append(callID); return operation == 3 }
    func stop() { stops += 1 }
}

final class SIPRegistrationTests: XCTestCase {
    @MainActor
    func testActualNativeRegistrationAuthenticatesAndClosesThroughTheAppAdapter() async throws {
        struct Account: Decodable { let user: String; let host: String; let port: Int; let password: String }
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "sip-account", withExtension: "json"))
        let account = try JSONDecoder().decode(Account.self, from: Data(contentsOf: url))
        guard account.host == "127.0.0.1", (1...65535).contains(account.port) else {
            XCTFail("Native SIP fixture must stay on loopback"); return
        }
        let network = NextSIPNetwork(start: false); network.update(.wifi)
        let context = try XCTUnwrap(network.snapshot().first?["interface"])
        let service = NextSIPRegistration(network: network, driver: { NextSIPNativeDriver() })
        let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        XCTAssertEqual(service.perform(["op": "open", "session": id, "interface": context])["ok"] as? Bool, true)
        defer { _ = service.perform(["op": "close", "session": id]) }
        XCTAssertEqual(service.perform(["op": "start", "session": id, "user": account.user,
            "host": account.host, "port": account.port, "password": account.password])["ok"] as? Bool, true)
        var registered = false
        for _ in 0..<150 {
            let events = service.perform(["op": "poll", "session": id])["events"] as? [[String: Any]] ?? []
            if events.contains(where: { $0["state"] as? String == "registered" }) { registered = true; break }
            if events.contains(where: { ["engine_failed", "stopped"].contains($0["state"] as? String ?? "") }) { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertTrue(registered, "The app adapter did not authenticate with the private registrar")
        _ = service.perform(["op": "close", "session": id])
        var closed = false
        for _ in 0..<60 {
            if service.perform(["op": "poll", "session": id])["closed"] as? Bool == true { closed = true; break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertTrue(closed, "The native account has not fully exited")
    }

    @MainActor
    func testSessionOwnershipLogoutAndLateEventsCannotAffectTheReplacement() throws {
        let network = NextSIPNetwork(start: false); network.update(.wifi)
        let context = try XCTUnwrap(network.snapshot().first?["interface"])
        let first = FakeNextSIPDriver(), second = FakeNextSIPDriver()
        var drivers = [first, second]
        let service = NextSIPRegistration(network: network, driver: { drivers.removeFirst() })
        let a = String(repeating: "a", count: 32), b = String(repeating: "b", count: 32)
        XCTAssertEqual(service.perform(["op": "open", "session": a, "interface": context])["ok"] as? Bool, true)
        XCTAssertTrue(first.accounts.isEmpty)
        let start: [String: Any] = ["op": "start", "session": a, "user": "9001", "host": "::1", "port": 55162, "password": "private test"]
        XCTAssertEqual(service.perform(start)["ok"] as? Bool, true)
        XCTAssertEqual(first.accounts.first?.host, "[::1]")
        first.events?("incoming", "not logged", 0, "native-incoming")
        XCTAssertEqual(first.rejections, ["native-incoming"])
        first.events?("registered", "not logged", 0, "")
        XCTAssertEqual((service.perform(["op": "poll", "session": a])["events"] as? [[String: Any]])?.first?["state"] as? String, "registered")
        XCTAssertEqual(service.perform(["op": "close", "session": a])["closed"] as? Bool, false)
        XCTAssertEqual(first.stops, 1)
        XCTAssertEqual(service.perform(["op": "open", "session": b, "interface": context])["ok"] as? Bool, false)
        first.exit?(0)
        XCTAssertEqual(service.perform(["op": "open", "session": b, "interface": context])["ok"] as? Bool, true)
        first.events?("registered", "", 0, ""); first.exit?(0)
        XCTAssertEqual((service.perform(["op": "poll", "session": b])["events"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual(service.perform(["op": "poll", "session": a])["ok"] as? Bool, false)
    }
    @MainActor
    func testChangedRouteCannotStartAnOldAccountAndCallingIsUnavailable() throws {
        let network = NextSIPNetwork(start: false); network.update(.wifi)
        let context = try XCTUnwrap(network.snapshot().first?["interface"])
        let driver = FakeNextSIPDriver(), id = String(repeating: "a", count: 32)
        let service = NextSIPRegistration(network: network, driver: { driver })
        XCTAssertEqual(service.perform(["op": "open", "session": id, "interface": context])["calling_available"] as? Bool, false)
        for op in ["dial", "answer", "mute", "speaker"] {
            XCTAssertEqual(service.perform(["op": op, "session": id])["ok"] as? Bool, false)
        }
        network.update(.mobile); service.networkChanged()
        XCTAssertEqual(service.perform(["op": "start", "session": id, "user": "9001", "host": "127.0.0.1", "port": 55162, "password": "private test"])["ok"] as? Bool, false)
        XCTAssertTrue(driver.accounts.isEmpty)
        XCTAssertEqual(service.perform(["op": "poll", "session": id])["closed"] as? Bool, true)
    }
}

@MainActor
private final class LinkedSIPCalls: NextSIPCallManaging {
    var controls: [[String: Any]] = []
    var received: [(String, String, String)] = []
    var closes = 0
    let emit: ([String: Any]) -> Void
    init(emit: @escaping ([String: Any]) -> Void) { self.emit = emit }
    func perform(_ value: [String: Any]) -> Bool { controls.append(value); return true }
    func receive(_ state: String, peer: String, code: Int32, id: String) {
        received.append((state, peer, id))
        emit(["state":state,"peer":peer,"native_id":id,"code":code])
    }
    func close() { closes += 1 }
}

extension SIPRegistrationTests {
    @MainActor
    func testLinkedCallingRequiresRegistrationAndClosesOnRouteRetirement() throws {
        let network = NextSIPNetwork(start:false); network.update(.wifi)
        let context = try XCTUnwrap(network.snapshot().first?["interface"])
        let driver = FakeNextSIPDriver(), id = String(repeating:"c",count:32)
        var calls: LinkedSIPCalls?
        let service = NextSIPRegistration(network:network,driver:{ driver },calls:{ _, emit in
            let value = LinkedSIPCalls(emit:emit); calls = value; return value
        })
        XCTAssertEqual(service.perform(["op":"capabilities"])["calling_available"] as? Bool,true)
        XCTAssertTrue(["granted", "denied", "not_determined", "unknown"].contains(
            service.perform(["op":"capabilities"])["microphone_permission"] as? String ?? ""))
        XCTAssertNil(calls)
        XCTAssertEqual(service.perform(["op":"open","session":id,"interface":context])["calling_available"] as? Bool,true)
        let dial: [String: Any] = ["op":"dial","session":id,"call_id":"native-call","peer":"sip:9002@127.0.0.1"]
        XCTAssertEqual(service.perform(dial)["ok"] as? Bool,false)
        XCTAssertEqual(service.perform(["op":"start","session":id,"user":"9001","host":"127.0.0.1","port":55162,"password":"synthetic"])["ok"] as? Bool,true)
        XCTAssertEqual(service.perform(dial)["ok"] as? Bool,false)
        driver.events?("registered","",0,"")
        XCTAssertEqual(service.perform(dial)["ok"] as? Bool,true)
        XCTAssertEqual(calls?.controls.count,1)
        driver.events?("incoming","sip:9002@127.0.0.1",0,"native-incoming")
        XCTAssertEqual(calls?.received.first?.1,"sip:9002@127.0.0.1")
        let events = service.perform(["op":"poll","session":id])["events"] as? [[String: Any]]
        XCTAssertEqual(events?.last?["native_id"] as? String,"native-incoming")
        network.update(.mobile); service.networkChanged()
        XCTAssertEqual(calls?.closes,1)
        XCTAssertEqual(driver.stops,1)
        XCTAssertEqual(service.perform(dial)["ok"] as? Bool,false)
    }
}
