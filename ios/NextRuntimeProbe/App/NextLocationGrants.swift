import Foundation

/// Native revocation survives a backend database write failure or restart.
/// Only random consent revisions are stored here, never positions or contacts.
@MainActor
final class NextLocationGrants {
    private let defaults: UserDefaults
    private let key = "next.location.authorized-revisions.v1"
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    func permitsResume(_ revisions: Set<String>) -> Bool {
        !revisions.isEmpty && revisions.isSubset(of: Set(defaults.stringArray(forKey: key) ?? []))
    }
    func replace(with revisions: Set<String>) { defaults.set(Array(revisions).sorted(), forKey: key) }
    func revoke() { replace(with: []) }
}
