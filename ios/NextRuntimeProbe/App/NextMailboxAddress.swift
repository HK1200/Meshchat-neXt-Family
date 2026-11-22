import Foundation

enum NextMailboxAddress {
    static func normalize(_ text: String) -> String? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard value.isEmpty || value.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return nil }
        return value
    }
}


struct NextMailboxState: Decodable {
    let address: String
    let send_fallback: Bool?
    let status: String
    let last_checked_at: Double?
    let error: String?
}
