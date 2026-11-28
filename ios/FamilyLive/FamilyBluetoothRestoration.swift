import Foundation

/// Quarantines OS-restored bytes until the backend reopens a currently enabled
/// saved radio. OS restoration itself does not approve a radio or its senders.
struct FamilyBluetoothRestoration {
    static let identifier = "org.meshchat.selected-radios.v1"
    static func shouldRestore(_ identifiers: [String]?) -> Bool {
        identifiers?.contains(identifier) == true
    }
    static let maximumRadios = 8
    static let maximumBytes = 65_536
    static let maximumPackets = 1000
    struct Pending {
        let generation: UInt64
        var packets: [Data] = []
        var bytes = 0
        var overflowed = false
    }
    private var pending: [UUID: Pending] = [:]
    private var sequence: UInt64 = 0

    mutating func remember(_ id: UUID) -> UInt64? {
        guard pending[id] == nil, pending.count < Self.maximumRadios else { return nil }
        sequence &+= 1
        pending[id] = Pending(generation: sequence)
        return sequence
    }
    func contains(_ id: UUID) -> Bool { pending[id] != nil }
    mutating func receive(_ data: Data, from id: UUID) {
        guard var entry = pending[id], !entry.overflowed, !data.isEmpty else { return }
        guard entry.packets.count < Self.maximumPackets,
              data.count <= Self.maximumBytes - entry.bytes else {
            entry.packets = []; entry.bytes = 0; entry.overflowed = true
            pending[id] = entry
            return
        }
        entry.packets.append(data); entry.bytes += data.count; pending[id] = entry
    }
    mutating func admit(_ id: UUID) -> Pending? { pending.removeValue(forKey: id) }
    @discardableResult mutating func remove(_ id: UUID) -> Bool { pending.removeValue(forKey: id) != nil }
    mutating func expire(_ id: UUID, generation: UInt64) -> Bool {
        guard pending[id]?.generation == generation else { return false }
        pending.removeValue(forKey: id)
        return true
    }
}
