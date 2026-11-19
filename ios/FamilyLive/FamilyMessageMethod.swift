import Foundation

enum FamilyMessageMethod: String, CaseIterable, Identifiable, Hashable, Sendable {
    case automatic = "auto", reticulum, meshcore
    var id: String { rawValue }
    var name: String {
        switch self {
        case .automatic: return "Automatic"
        case .reticulum: return "Reticulum"
        case .meshcore: return "MeshCore"
        }
    }
    var addressKey: String { self == .meshcore ? "meshcore" : "lxmf" }
}

struct FamilyMessageRoute: Decodable, Sendable {
    let service: String
    let reason: String
}

struct FamilyMessagePolicy {
    let approved: [FamilyMessageMethod]
    let available: [FamilyMessageMethod]
    let text: String
    let hasAttachments: Bool

    init(original: FamilyContact, current: FamilyContact?, routes: [FamilyMessageRoute], text: String, hasAttachments: Bool) {
        self.text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        self.hasAttachments = hasAttachments
        // Automatic delivery can use either approved service. Stop a stale chat
        // when either messaging address changes, rather than ranking an old view.
        let unchanged = current?.id == original.id && ["lxmf", "meshcore"].allSatisfy {
            current?.addresses[$0] == original.addresses[$0]
        }
        let methods: [FamilyMessageMethod] = [.reticulum, .meshcore]
        let approvedMethods = unchanged ? methods.filter { original.addresses[$0.addressKey]?.isEmpty == false } : []
        approved = approvedMethods
        available = routes.compactMap { FamilyMessageMethod(rawValue: $0.service) }
            .filter { approvedMethods.contains($0) }
    }

    func issue(for method: FamilyMessageMethod) -> String? {
        if approved.isEmpty { return "Contact approval changed or no messaging address is approved. Reopen this conversation." }
        if text.unicodeScalars.count > 4096 { return "Messages allow up to 4,096 characters." }
        if method != .automatic && !approved.contains(method) { return "Contact approval changed. Reopen this conversation." }
        if hasAttachments {
            if method == .meshcore { return "Files and photos require Reticulum. Choose Automatic or Reticulum." }
            if !available.contains(.reticulum) { return "Files and photos need an approved Reticulum connection." }
            return nil
        }
        let eligible = available.filter { $0 != .meshcore || text.utf8.count <= 160 }
        if method == .automatic {
            if eligible.isEmpty {
                return available.contains(.meshcore) && text.utf8.count > 160
                    ? "MeshCore allows up to 160 bytes. Shorten the message or connect Reticulum."
                    : "No approved messaging connection is available right now."
            }
        } else {
            if method == .meshcore && text.utf8.count > 160 { return "MeshCore allows up to 160 bytes. Shorten the message or choose Reticulum." }
            if !eligible.contains(method) { return "\(method.name) is unavailable for this contact. Choose Automatic to use another connection." }
        }
        return nil
    }
}
