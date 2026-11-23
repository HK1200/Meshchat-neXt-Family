// SPDX-License-Identifier: 0BSD
import Foundation

/// Only the bundled opaque Nomad renderer may load as a child frame.
/// This grants no native bridge, arbitrary frame URL or private API access.
enum NextNomadFramePolicy {
    static func allows(_ target: URL?, base: URL) -> Bool {
        guard let target, base.scheme == "http", base.host == "127.0.0.1", base.port != nil,
              target.scheme == base.scheme, target.host == base.host, target.port == base.port,
              target.user == nil, target.password == nil, target.fragment == nil,
              target.path == "/nomad-crash-tab.html",
              let parts = URLComponents(url: target, resolvingAgainstBaseURL: false) else { return false }
        let items = parts.queryItems ?? []
        guard items.count <= 2, Set(items.map(\.name)).count == items.count else { return false }
        return items.allSatisfy { item in
            guard let value = item.value, !value.isEmpty, value.utf8.count <= 256,
                  !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { return false }
            switch item.name {
            case "v": return true
            case "t": return value.utf8.count <= 20 && value.range(of: "^[0-9]+$", options: .regularExpression) != nil
            default: return false
            }
        }
    }
}
