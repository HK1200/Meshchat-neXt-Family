import Foundation

struct NextMeshCoreAlertTarget: Decodable {
    let owner: String
    let target: String
    let kind: String
    let radio_id: String?

    var fragment: String? {
        guard owner.utf8.count == 64, target.utf8.count == 64,
              owner.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              target.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { return nil }
        if let radio_id {
            guard (1...64).contains(radio_id.utf8.count), radio_id.utf8.allSatisfy({
                (97...122).contains($0) || (48...57).contains($0) || $0 == 45
            }) else { return nil }
        }
        let suffix = radio_id.map { "meshcoreRadio=" + $0 } ?? ""
        switch kind {
        case "direct": return "/messages?meshcore=" + target + (suffix.isEmpty ? "" : "&" + suffix)
        case "room": return "/meshcore/nodes/" + target + (suffix.isEmpty ? "" : "?" + suffix)
        case "channel": return "/meshcore/channels/" + target + (suffix.isEmpty ? "" : "?" + suffix)
        default: return nil
        }
    }
}
