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
