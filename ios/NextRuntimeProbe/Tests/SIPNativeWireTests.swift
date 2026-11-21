import XCTest
import Darwin

@MainActor
private final class WireCallAudio: NextSIPCallAudio {
    var preparations = 0
    func prepare(managed: Bool) async -> Bool { preparations += 1; return true }
    func speaker(_ enabled: Bool) -> Bool { false }
    func finish(managed: Bool) {}
}
@MainActor
private final class WireSystemDriver: FamilySystemCallDriver {
    weak var events: (any FamilySystemCallEvents)?
    func incoming(_ id: UUID, name: String) async throws { XCTFail("Private wire test must not invoke CallKit") }
    func start(_ id: UUID, name: String) async throws { XCTFail("Private wire test must not invoke CallKit") }
    func answer(_ id: UUID) async throws { XCTFail("Private wire test must not invoke CallKit") }
    func end(_ id: UUID) async throws { XCTFail("Private wire test must not invoke CallKit") }
    func mute(_ id: UUID, muted: Bool) async throws { XCTFail("Private wire test must not invoke CallKit") }
    func connected(_ id: UUID) {}
    func ended(_ id: UUID, failed: Bool) {}
}

final class SIPNativeWireTests: XCTestCase {
    @MainActor
    func testForegroundRecoverySignalReachesTheEmbeddedRuntime() {
        let before = next_probe_listener_generation()
        next_probe_request_listener_recovery()
        XCTAssertEqual(next_probe_listener_generation(), before + 1)
    }

    func testActualHostDeclaresTheCallKitBackgroundModes() {
        let modes = Bundle.main.object(forInfoDictionaryKey: "UIBackgroundModes") as? [String] ?? []
        XCTAssertTrue(Set(["audio", "voip"]).isSubset(of: Set(modes)))
        let microphone = Bundle.main.object(forInfoDictionaryKey: "NSMicrophoneUsageDescription") as? String ?? ""
        XCTAssertFalse(microphone.isEmpty)
    }

    @MainActor
    func testActualNativeOutgoingRequestReceivesBusyAndCloses() async throws {
        try await exercise("outgoing")
    }
    @MainActor
    func testActualNativeIncomingCallCanBeDeclinedWithoutMicrophoneAccess() async throws {
        try await exercise("incoming")
    }

    @MainActor
    private func exercise(_ direction: String) async throws {
        continueAfterFailure = false
        struct Account: Decodable { let user: String; let host: String; let port: Int; let password: String }
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "sip-\(direction)", withExtension: "json"))
        let account = try JSONDecoder().decode(Account.self, from: Data(contentsOf: url))
        if direction == "incoming" { XCTAssertEqual(account.host, "127.0.0.1") }
        else {
            XCTAssertNotEqual(account.host, "127.0.0.1")
            XCTAssertTrue(localIPv4Addresses().contains(account.host), "The SIP peer must be bound to this simulator host")
        }
        XCTAssertTrue((1...65535).contains(account.port))
        let network = NextSIPNetwork(start: false); network.update(.wifi)
        let context = try XCTUnwrap(network.snapshot().first?["interface"])
        let audio = WireCallAudio()
        let system = FamilySystemCalls(driver: WireSystemDriver(), preferences: nil, enabled: false)
        let service = NextSIPRegistration(network: network, driver: { NextSIPNativeDriver() }, calls: { driver, emit in
            NextSIPCallSession(driver: driver, system: system, audio: audio, observeAudio: false, emit: emit)
        })
        let session = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        XCTAssertEqual(service.perform(["op":"open","session":session,"interface":context])["ok"] as? Bool,true)
        defer { _ = service.perform(["op":"close","session":session]) }
        XCTAssertEqual(service.perform(["op":"start","session":session,"user":account.user,
            "host":account.host,"port":account.port,"password":account.password])["ok"] as? Bool,true)
        var observed: [[String: Any]] = []
        func collect() {
            observed += service.perform(["op":"poll","session":session])["events"] as? [[String: Any]] ?? []
        }
        for _ in 0..<200 {
            collect()
            if observed.contains(where: { $0["state"] as? String == "registered" }) { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertTrue(observed.contains(where: { $0["state"] as? String == "registered" }))
        let callID: String
        if direction == "outgoing" {
            callID = "private-outgoing-" + UUID().uuidString
            XCTAssertEqual(service.perform(["op":"dial","session":session,"call_id":callID,
                "peer":"sip:private-peer@\(account.host):\(account.port)"])["ok"] as? Bool,true)
        } else {
            for _ in 0..<200 {
                collect()
                if observed.contains(where: { $0["state"] as? String == "incoming" }) { break }
                try await Task.sleep(for: .milliseconds(100))
            }
            let incoming = try XCTUnwrap(observed.first(where: { $0["state"] as? String == "incoming" }))
            callID = try XCTUnwrap(incoming["native_id"] as? String)
            XCTAssertEqual(service.perform(["op":"hangup","session":session,"call_id":callID])["ok"] as? Bool,true)
        }
        for _ in 0..<200 {
            collect()
            if observed.contains(where: { $0["state"] as? String == "ended" && $0["native_id"] as? String == callID }) { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertTrue(observed.contains(where: { $0["state"] as? String == "ended" && $0["native_id"] as? String == callID }))
        XCTAssertEqual(audio.preparations, direction == "outgoing" ? 1 : 0)
        let failures = observed.filter { ["engine_failed", "audio_error", "command_failed"].contains($0["state"] as? String ?? "") }
        XCTAssertTrue(failures.isEmpty, "Native signaling errors: " + failures.map {
            "\($0["state"] as? String ?? "unknown") code=\($0["code"] as? Int ?? -1)"
        }.joined(separator: ", "))
        _ = service.perform(["op":"close","session":session])
        var closed = false
        for _ in 0..<100 {
            if service.perform(["op":"poll","session":session])["closed"] as? Bool == true { closed = true; break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertTrue(closed, "Private native SIP transport did not unregister and exit")
    }

    private func localIPv4Addresses() -> Set<String> {
        var first: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&first) == 0 else { return [] }
        defer { if let first { freeifaddrs(first) } }
        var values = Set<String>()
        var cursor = first
        while let row = cursor {
            if let address = row.pointee.ifa_addr, address.pointee.sa_family == UInt8(AF_INET) {
                var name = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                if getnameinfo(address, socklen_t(address.pointee.sa_len), &name, socklen_t(name.count), nil, 0, NI_NUMERICHOST) == 0 {
                    values.insert(String(cString: name))
                }
            }
            cursor = row.pointee.ifa_next
        }
        return values
    }

}
