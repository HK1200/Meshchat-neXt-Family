import Foundation

struct NextFamilyCard {
    private struct Response: Decodable { let contact_card: String }
    private struct Contact: Decodable {
        let format: String
        let version: Int
        let name: String
        let addresses: [String: String]
        let identityPublicKey: String
    }
    static func payload(from data: Data, expectedAddress: String) throws -> String {
        guard data.count <= 16384 else { throw URLError(.cannotParseResponse) }
        let text = try JSONDecoder().decode(Response.self, from: data).contact_card
        guard text.utf8.count <= 8192, let raw = text.data(using: .utf8),
              let dictionary = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
              Set(dictionary.keys).isSubset(of: ["format", "version", "name", "addresses", "identityPublicKey"]) else {
            throw URLError(.cannotParseResponse)
        }
        let card = try JSONDecoder().decode(Contact.self, from: raw)
        guard card.format == "next-family-contact", card.version == 1,
              !card.name.isEmpty, card.name.count <= 64,
              card.addresses["lxmf"] == expectedAddress.lowercased(),
              card.addresses["lxmf"]?.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              Set(card.addresses.keys).isSubset(of: ["lxmf", "lxst"]),
              card.identityPublicKey.range(of: "^[a-f0-9]{128}$", options: .regularExpression) != nil else {
            throw URLError(.cannotParseResponse)
        }
        if let voice = card.addresses["lxst"], voice.range(of: "^[a-f0-9]{32}$", options: .regularExpression) == nil {
            throw URLError(.cannotParseResponse)
        }
        return text
    }
}

