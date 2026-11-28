import Foundation

/// Serial-queue-owned leases for the existing three 20 ms playback buffers.
/// A completed buffer makes room immediately, independent of a delayed timer.
struct FamilyVoicePlaybackClock {
    private var leases: Set<UInt64> = []
    private var nextLease: UInt64 = 0
    private(set) var running = false
    var scheduled: Int { leases.count }
    var available: Int { running ? 3 - leases.count : 0 }

    mutating func start() { running = true }
    mutating func stop() { running = false; leases.removeAll() }

    mutating func schedule() -> UInt64? {
        guard available > 0 else { return nil }
        repeat { nextLease &+= 1 } while leases.contains(nextLease)
        leases.insert(nextLease)
        return nextLease
    }

    mutating func consumed(_ lease: UInt64) -> Bool {
        guard running, leases.remove(lease) != nil else { return false }
        return true
    }
}
