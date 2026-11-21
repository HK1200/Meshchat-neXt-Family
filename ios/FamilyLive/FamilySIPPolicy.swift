import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

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

    static func normalizedHost(_ raw: String) -> String? {
        var value = raw.lowercased()
        if value.hasPrefix("[") && value.hasSuffix("]") { value = String(value.dropFirst().dropLast()) }
        if value.contains(":") {
            var address = in6_addr()
            guard value.withCString({ inet_pton(AF_INET6, $0, &address) }) == 1 else { return nil }
            var buffer = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
            guard inet_ntop(AF_INET6, &address, &buffer, socklen_t(INET6_ADDRSTRLEN)) != nil else { return nil }
            return String(cString: buffer)
        }
        guard value.range(of: "^[a-z0-9][a-z0-9.-]{0,252}$", options: .regularExpression) != nil else { return nil }
        return value
    }
    static func hostForURI(_ host: String) -> String { host.contains(":") ? "[\(host)]" : host }
    var uri: String { "sip:\(user)@\(Self.hostForURI(host)):\(port)" }

    func matches(_ incoming: FamilySIPAddress, providerHost: String, providerPort: Int, resolvedHosts: Set<String>) -> Bool {
        if self == incoming { return true }
        guard let provider = Self.normalizedHost(providerHost) else { return false }
        return user == incoming.user && host == provider && port == providerPort &&
            (incoming.port == port || incoming.port == 5060) &&
            (incoming.host == provider || resolvedHosts.contains { Self.normalizedHost($0) == incoming.host })
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
        let server = parts.count == 2 ? String(parts[1]) : Self.hostForURI(Self.normalizedHost(defaultHost) ?? "") + ":" + String(defaultPort)
        let hostText: String
        let port: Int?
        if server.hasPrefix("[") {
            guard let end = server.firstIndex(of: "]") else { return nil }
            hostText = String(server[server.index(after: server.startIndex)..<end])
            guard hostText.contains(":"), Self.normalizedHost(hostText) != nil else { return nil }
            let suffix = String(server[server.index(after: end)...])
            if suffix.isEmpty { port = 5060 }
            else {
                guard suffix.hasPrefix(":"), suffix.dropFirst().allSatisfy({ $0.isASCII && $0.isNumber }) else { return nil }
                port = Int(suffix.dropFirst())
            }
        } else {
            let hostParts = server.split(separator: ":", omittingEmptySubsequences: false)
            guard hostParts.count <= 2, let hostPart = hostParts.first else { return nil }
            hostText = String(hostPart)
            port = hostParts.count == 2 ? Int(hostParts[1]) : 5060
        }
        guard user.range(of: "^[A-Za-z0-9_.+~*-]{1,128}$", options: .regularExpression) != nil,
              let host = Self.normalizedHost(hostText),
              let port, (1...65535).contains(port) else { return nil }
        self.user = user
        self.host = host
        self.port = port
    }
}
