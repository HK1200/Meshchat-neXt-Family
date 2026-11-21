import XCTest
import Darwin

final class VoiceCodecTests: XCTestCase {
    func testBundledLXSTEncodesAndDecodesAllMobileVoiceProfiles() async throws {
        struct Check: Decodable {
            let codec: String
            let setting: Int
            let samples: Int
            let sample_rate: Int
            let rms: Double
        }
        struct Report: Decodable {
            let ok: Bool
            let checks: [Check]
            let microphone_used: Bool
            let network_used: Bool
        }
        let data = try await Task.detached(priority: .utility) {
            for _ in 0..<300 {
                if let reply = next_probe_check_voice_codecs() {
                    defer { free(reply) }
                    return Data(String(cString: reply).utf8)
                }
                try await Task.sleep(for: .milliseconds(100))
            }
            throw NSError(domain: "VoiceCodecTests", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "The bundled Python runtime did not start"])
        }.value
        let status = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        guard status["ok"] as? Bool == true else {
            XCTFail(String(data: data, encoding: .utf8) ?? "No codec diagnostic")
            return
        }
        let report = try JSONDecoder().decode(Report.self, from: data)
        XCTAssertTrue(report.ok)
        XCTAssertFalse(report.microphone_used)
        XCTAssertFalse(report.network_used)
        XCTAssertEqual(report.checks.count, 10)
        let opus = report.checks.filter { $0.codec == "opus" }
        let codec2 = report.checks.filter { $0.codec == "codec2" }
        XCTAssertEqual(Set(opus.map(\.setting)), Set([0, 1, 2]))
        XCTAssertEqual(Set(codec2.map(\.setting)), Set([700, 1200, 1300, 1400, 1600, 2400, 3200]))
        for check in report.checks {
            XCTAssertTrue(check.rms.isFinite)
            XCTAssertGreaterThan(check.rms, 0.00001)
            XCTAssertEqual(check.samples, check.codec == "opus" ? 960 : 320)
            XCTAssertEqual(check.sample_rate, check.codec == "opus" ? 48000 : 8000)
        }
    }
}
