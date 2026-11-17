import Foundation

struct FamilySIPAccount: Codable, Equatable, Sendable {
    var enabled: Bool
    var user: String
    var host: String
    var port: Int
    var password: String
}

struct FamilySIPAddress: Equatable, Sendable {
    let user: String
    let host: String
    let port: Int

    var uri: String { "sip:\(user)@\(host):\(port)" }

    func matches(_ incoming: FamilySIPAddress, providerHost: String, providerPort: Int, resolvedHosts: Set<String>) -> Bool {
        if self == incoming { return true }
        return user == incoming.user && host == providerHost.lowercased() && port == providerPort &&
            (incoming.port == port || incoming.port == 5060) &&
            (incoming.host == providerHost.lowercased() || resolvedHosts.contains(incoming.host))
    }

    init?(_ raw: String, defaultHost: String = "premium.hamsoverip.com", defaultPort: Int = 5160) {
        guard raw.utf8.count <= 512, !raw.contains("\r"), !raw.contains("\n") else { return nil }
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let start = value.firstIndex(of: "<"), let end = value[start...].firstIndex(of: ">") {
            value = String(value[value.index(after: start)..<end])
        }
        if value.lowercased().hasPrefix("sip:") { value = String(value.dropFirst(4)) }
        value = String(value.split(separator: ";", maxSplits: 1).first ?? "")
        let parts = value.split(separator: "@", omittingEmptySubsequences: false)
        guard parts.count == 1 || parts.count == 2 else { return nil }
        let user = String(parts[0])
        let server = parts.count == 2 ? String(parts[1]) : defaultHost + ":" + String(defaultPort)
        let hostParts = server.split(separator: ":", omittingEmptySubsequences: false)
        guard hostParts.count <= 2, let hostPart = hostParts.first else { return nil }
        let host = String(hostPart).lowercased()
        let port = hostParts.count == 2 ? Int(hostParts[1]) : 5060
        guard user.range(of: "^[A-Za-z0-9_.+~*-]{1,128}$", options: .regularExpression) != nil,
              host.range(of: "^[a-z0-9][a-z0-9.-]{0,252}$", options: .regularExpression) != nil,
              let port, (1...65535).contains(port) else { return nil }
        self.user = user
        self.host = host
        self.port = port
    }
}

