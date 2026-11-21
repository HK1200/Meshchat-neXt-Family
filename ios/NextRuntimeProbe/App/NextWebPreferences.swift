import Foundation
import CoreFoundation

/// Explicit UI preferences only. Transport passwords and session credentials
/// have no storage path through this whitelist.
final class NextWebPreferences {
    static let featureKey = "meshchat-next.app-features.v1"
    static let contactsKey = "meshchat-next.sip.contacts.v1"
    static let keys: Set<String> = [featureKey, contactsKey, "meshchatnext.sidebar.app", "meshchatnext.sidebar.messages"]
    private let file: URL
    private(set) var values: [String: String]
    init(folder: URL) throws {
        file = folder.appendingPathComponent("next-web-preferences.json")
        values = try Self.read(file)
    }
    private static func read(_ file: URL) throws -> [String: String] {
        guard FileManager.default.fileExists(atPath: file.path) else { return [:] }
        let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
        guard size <= 262144 else { throw CocoaError(.fileReadCorruptFile) }
        let data = try Data(contentsOf: file)
        guard let values = try JSONSerialization.jsonObject(with: data) as? [String: String],
              values.allSatisfy({ Self.valid($0.value, for: $0.key) }) else { throw CocoaError(.fileReadCorruptFile) }
        return values
    }
    private static func valid(_ value: String, for key: String) -> Bool {
        guard keys.contains(key), value.utf8.count <= 131072 else { return false }
        if key.hasPrefix("meshchatnext.sidebar.") { return value == "true" || value == "false" }
        guard let data = value.data(using: .utf8), let object = try? JSONSerialization.jsonObject(with: data) else { return false }
        if key == featureKey {
            guard let features = object as? [String: Any], Set(features.keys).isSubset(of: ["reticulum", "meshcore", "sip"]) else { return false }
            return features.values.allSatisfy { value in
                guard let number = value as? NSNumber else { return false }
                return CFGetTypeID(number) == CFBooleanGetTypeID()
            }
        }
        guard let contacts = object as? [[String: Any]], contacts.count <= 512 else { return false }
        let fields: Set<String> = ["id", "name", "address", "numbers", "linked_contact"]
        var ids = Set<String>()
        for contact in contacts {
            guard Set(contact.keys).isSubset(of: fields),
                  let id = contact["id"] as? String, !id.isEmpty, id.utf8.count <= 128, ids.insert(id).inserted,
                  let name = contact["name"] as? String, !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, name.utf16.count <= 100,
                  let address = contact["address"] as? String, validAddress(address) else { return false }
            if let linked = contact["linked_contact"], (linked as? String).map({ $0.utf8.count <= 256 }) != true { return false }
            if let numbers = contact["numbers"] {
                guard let rows = numbers as? [[String: Any]], !rows.isEmpty, rows.count <= 12 else { return false }
                for number in rows {
                    guard Set(number.keys) == Set(["label", "address"]),
                          let label = number["label"] as? String, ["Home", "Office", "Mobile", "Other"].contains(label),
                          let address = number["address"] as? String, validAddress(address) else { return false }
                }
            }
        }
        return true
    }
    private static func validAddress(_ value: String) -> Bool {
        !value.isEmpty && value.utf16.count <= 320 && !value.contains(where: { $0 == "\0" || $0 == "\r" || $0 == "\n" })
    }
    func apply(_ request: [String: Any]) throws {
        guard let op = request["op"] as? String else { throw CocoaError(.coderInvalidValue) }
        // All bridge writes run on the main actor. Read the latest snapshot so
        // another window cannot overwrite unrelated saved preferences.
        var next = try Self.read(file)
        if op == "clear" {
            guard Set(request.keys) == Set(["op"]) else { throw CocoaError(.coderInvalidValue) }
            next.removeAll()
        } else {
            guard let key = request["key"] as? String, Self.keys.contains(key) else { throw CocoaError(.coderInvalidValue) }
            if op == "remove" {
                guard Set(request.keys) == Set(["op", "key"]) else { throw CocoaError(.coderInvalidValue) }
                next.removeValue(forKey: key)
            } else if op == "set" {
                guard Set(request.keys) == Set(["op", "key", "value"]), let value = request["value"] as? String,
                      Self.valid(value, for: key) else { throw CocoaError(.coderInvalidValue) }
                next[key] = value
            } else { throw CocoaError(.coderInvalidValue) }
        }
        let data = try JSONSerialization.data(withJSONObject: next, options: [.sortedKeys])
        guard data.count <= 262144 else { throw CocoaError(.fileWriteOutOfSpace) }
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try data.write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        values = next
    }
}
