import XCTest
import Darwin

final class VoiceCodecTests: XCTestCase {
    func testBundledLXSTEncodesAndDecodesAllMobileVoiceProfiles() async throws {
        // This is an explicit bundled-runtime integration test. Model-test
        // hosts intentionally do not start CPython as a view side effect.
        _ = try await NextRuntimeLauncher.shared.session(configuration: nil)
        struct Check: Decodable {
            let codec: String
            let setting: Int
            let samples: Int
            let sample_rate: Int
            let rms: Double
        }
        struct VoiceNote: Decodable {
            let ok: Bool
            let mode: Int
            let encoded_bytes: Int
            let decoded_bytes: Int
            let rms: Double
            let frequency: Double
            let network_used: Bool
            let microphone_used: Bool
        }
        struct Report: Decodable {
            let ok: Bool
            let checks: [Check]
            let voice_note: VoiceNote
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
        XCTAssertTrue(report.voice_note.ok)
        XCTAssertEqual(report.voice_note.mode, 16)
        XCTAssertGreaterThan(report.voice_note.encoded_bytes, 0)
        XCTAssertLessThan(report.voice_note.encoded_bytes, 12000)
        XCTAssertGreaterThan(report.voice_note.decoded_bytes, 30000)
        XCTAssertLessThan(report.voice_note.decoded_bytes, 34000)
        XCTAssertGreaterThan(report.voice_note.rms, 1000)
        XCTAssertEqual(report.voice_note.frequency, 440, accuracy: 5)
        XCTAssertFalse(report.voice_note.network_used)
        XCTAssertFalse(report.voice_note.microphone_used)
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
