import Foundation

/// Routes bounded private bridge requests; neither provider writes secrets to disk.
final class NextCredentials {
    static let shared = NextCredentials()
    private let meshcore: NextMeshCoreSecrets
    private let sip: NextSIPPasswords
    init(meshcore: NextMeshCoreSecrets = .shared, sip: NextSIPPasswords = NextSIPPasswords()) {
        self.meshcore = meshcore; self.sip = sip
    }

    func request(_ text: String) -> String {
        guard text.utf8.count <= 16 * 1024, let data = text.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "{\"ok\":false}"
        }
        if value["domain"] == nil { return meshcore.request(text) }
        guard value["domain"] as? String == "sip" else { return "{\"ok\":false}" }
        do {
            let reply = try sip.perform(value)
            return String(decoding: try JSONSerialization.data(withJSONObject: reply), as: UTF8.self)
        } catch { return "{\"ok\":false}" }
    }
}
