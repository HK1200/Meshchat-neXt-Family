import Foundation

struct NextSIPAccountDraft: Equatable {
    var id = ""
    var label = ""
    var user = ""
    var host = "premium.hamsoverip.com"
    var port = "5160"
    var password = ""
    var savePassword = true
    var wifi = true
    var mobile = true
    var ethernet = true
    var allowedNetworks: [String] {
        [("wifi", wifi), ("mobile", mobile), ("ethernet", ethernet)].compactMap { $0.1 ? $0.0 : nil }
    }
    var payload: [String: Any]? {
        guard !allowedNetworks.isEmpty, let port = Int(port), (1...65535).contains(port),
              user.range(of: "^[A-Za-z0-9_.-]{1,64}$", options: .regularExpression) != nil,
              host.range(of: "^[A-Za-z0-9.-]{1,253}$", options: .regularExpression) != nil,
              !host.contains(".."), label.count <= 80, !label.unicodeScalars.contains(where: { $0.value < 32 }),
              !password.contains("\0"), password.utf8.count <= 256,
              !id.isEmpty || !password.isEmpty else { return nil }
        var account: [String: Any] = ["label": label.isEmpty ? user : label, "extension": user,
            "host": host, "port": port, "allowed_networks": allowedNetworks, "save_password": savePassword]
        if !id.isEmpty { account["id"] = id }
        var result: [String: Any] = ["op": "save", "account": account]
        if !password.isEmpty { result["password"] = password }
        return result
    }
}

