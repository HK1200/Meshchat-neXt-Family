import CoreFoundation
import Foundation

/// A bounded command contains session consent, never contact names or coordinates.
struct NextLocationCommand {
    enum Operation: String, Equatable { case start, resume, configure, status, stop, suspend }
    let operation: Operation
    let session: String
    let active: Bool
    let until: TimeInterval
    let background: Bool
    let revisions: Set<String>

    init(_ raw: [String: Any], now: TimeInterval = Date().timeIntervalSince1970) throws {
        guard Set(raw.keys).isSubset(of: ["op", "session", "active", "until", "background", "revisions"]),
              let op = raw["op"] as? String, let operation = Operation(rawValue: op),
              let session = raw["session"] as? String, Self.identifier(session),
              let active = Self.boolean(raw["active"]), let background = Self.boolean(raw["background"]),
              let until = raw["until"] as? NSNumber, CFGetTypeID(until) != CFBooleanGetTypeID(),
              until.doubleValue.isFinite,
              let revisions = raw["revisions"] as? [String], revisions.count <= 16,
              revisions.allSatisfy(Self.identifier), Set(revisions).count == revisions.count else {
            throw Failure.invalid
        }
        let deadline = until.doubleValue
        guard active == !revisions.isEmpty,
              !active || deadline == -1 || (deadline > now && deadline <= now + 3605),
              active || deadline == 0,
              ![.start, .resume].contains(operation) || active,
              ![.stop, .suspend].contains(operation) || !active else { throw Failure.invalid }
        self.operation = operation; self.session = session; self.active = active
        self.until = deadline; self.background = background; self.revisions = Set(revisions)
    }

    static func identifier(_ value: String) -> Bool {
        value.utf8.count == 32 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    private static func boolean(_ value: Any?) -> Bool? {
        guard let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }
    enum Failure: Error { case invalid }
}
