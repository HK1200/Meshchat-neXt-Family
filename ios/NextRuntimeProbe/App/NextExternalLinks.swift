import Foundation

/// External pages never receive a native backend request or its credentials.
/// Only an explicit WebKit link activation may leave the embedded interface.
enum NextExternalLinks {
    static func allows(_ url: URL?, userActivated: Bool) -> Bool {
        guard userActivated, let url, url.absoluteString.utf8.count <= 8192,
              let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = url.host, !host.isEmpty, url.user == nil, url.password == nil else { return false }
        return true
    }
}
