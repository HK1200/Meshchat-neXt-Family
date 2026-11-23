// SPDX-License-Identifier: 0BSD
import Foundation
import Security

@MainActor
protocol NextCallWakeReplayStoring {
    func read() throws -> Data?
    func write(_ data: Data) throws
}

private enum NextCallWakeReplayError: Error { case unavailable }

@MainActor
private struct NextCallWakeReplayKeychain: NextCallWakeReplayStoring {
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: (Bundle.main.bundleIdentifier ?? "org.meshchat.next.ios") + ".call-wake-replay",
         kSecAttrAccount as String: "recent-call-identifiers"]
    }
    func read() throws -> Data? {
        var request = query; request[kSecReturnData as String] = true
        var item: CFTypeRef?
        let result = SecItemCopyMatching(request as CFDictionary, &item)
        if result == errSecItemNotFound { return nil }
        guard result == errSecSuccess, let data = item as? Data else { throw NextCallWakeReplayError.unavailable }
        return data
    }
    func write(_ data: Data) throws {
        guard data.count <= 65536 else { throw NextCallWakeReplayError.unavailable }
        let result = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if result == errSecSuccess { return }
        guard result == errSecItemNotFound else { throw NextCallWakeReplayError.unavailable }
        var request = query; request[kSecValueData as String] = data
        request[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(request as CFDictionary, nil) == errSecSuccess else { throw NextCallWakeReplayError.unavailable }
    }
}

/// Admission and transport handoff only. This does not register PushKit, enroll
/// a provider, start Python, acquire background time or request any permission.
@MainActor
final class NextReticulumWakeRouter: NextIncomingCallWakeRouting {
    static let shared = NextReticulumWakeRouter(system: .shared)
    enum Decision: Equatable { case accepted(UUID), duplicate(UUID), denied, busy, unavailable }
    typealias Delay = @MainActor @Sendable (TimeInterval) async throws -> Void
    private struct Ledger: Codable { let version: Int; var records: [String: TimeInterval] }
    private struct Pending {
        let id: UUID
        let voice: String
        let key: FamilySystemCallKey
        let expires: TimeInterval
        let issued: Int
        let intent: FamilyCallWake
        let permitted: @MainActor () -> Bool
    }
    private let system: FamilySystemCalls
    private let store: any NextCallWakeReplayStoring
    private let now: () -> Date
    private let delay: Delay
    private var pending: Pending?
    private var deadline: Task<Void, Never>?
    private(set) var status = "Off"

    init(system: FamilySystemCalls, store: (any NextCallWakeReplayStoring)? = nil,
         now: @escaping () -> Date = Date.init,
         delay: @escaping Delay = { try await Task.sleep(for: .seconds($0)) }) {
        self.system = system; self.store = store ?? NextCallWakeReplayKeychain()
        self.now = now; self.delay = delay
    }

    func accept(_ payload: Data, recipientPrivateKey: Data, recipientPublicKey: Data,
                audience: String, approvedNames: [String: String],
                permitted: @escaping @MainActor () -> Bool) -> Decision {
        refresh()
        let time = now().timeIntervalSince1970
        guard permitted(), time.isFinite, time >= 0, time <= 9_007_199_254_740_991 else { return .denied }
        let wake: FamilyCallWake
        do {
            wake = try FamilyCallWake.decode(payload, recipientPrivateKey: recipientPrivateKey,
                recipientPublicKey: recipientPublicKey, audience: audience,
                approvedCallers: Set(approvedNames.keys), now: Int(time))
        } catch { return .denied }
        let remaining = min(30, Double(wake.issued) + 30 - time)
        guard remaining > 0 else { return .denied }
        let call = wake.call.uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        let replayKey = wake.recipient + "/" + call
        do {
            var ledger = Ledger(version: 1, records: [:])
            if let saved = try store.read() {
                guard saved.count <= 65536 else { return .unavailable }
                ledger = try JSONDecoder().decode(Ledger.self, from: saved)
                guard ledger.version == 1, ledger.records.count <= 256,
                      ledger.records.allSatisfy({ key, value in
                          key.range(of: "^[a-f0-9]{32}/[a-f0-9]{32}$", options: .regularExpression) != nil &&
                          value.isFinite && value >= 0 && value <= 9_007_199_254_740_991
                      }) else { return .unavailable }
            }
            ledger.records = ledger.records.filter { $0.value > time }
            if ledger.records[replayKey] != nil { return .duplicate(wake.call) }
            guard pending == nil, !system.hasCall, system.enabled else { return .busy }
            guard ledger.records.count < 256 else { return .unavailable }
            // Persist before reporting, including across a process crash. Never
            // ring if Keychain is unavailable or a saved replay record is corrupt.
            ledger.records[replayKey] = time + 120
            try store.write(JSONEncoder().encode(ledger))
        } catch { return .unavailable }
        let key = FamilySystemCallKey(service: .reticulum, id: "wake-" + call)
        let name = String((approvedNames[wake.callerVoice] ?? "Approved caller")
            .filter { !$0.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) }.prefix(128))
        let actions = FamilySystemCallActions(prepareAudio: { false }, start: { false }, answer: { false },
            end: { [weak self] in self?.cancel(wake.call) }, mute: { _ in false })
        guard system.reserveIncoming(key, id: wake.call, name: name.isEmpty ? "Approved caller" : name, actions: actions) else {
            return .busy
        }
        pending = Pending(id: wake.call, voice: wake.callerVoice, key: key, expires: time + remaining, issued: wake.issued, intent: wake, permitted: permitted)
        status = "Waiting for the approved caller"
        let pause = delay
        deadline = Task { @MainActor [weak self] in
            do {
                try Task.checkCancellation()
                try await pause(remaining)
                try Task.checkCancellation()
                self?.cancel(wake.call)
            } catch { }
        }
        return .accepted(wake.call)
    }

    func refresh() {
        guard let pending else { return }
        let time = now().timeIntervalSince1970
        if !pending.permitted() || !time.isFinite || time < max(0, Double(pending.issued) - 10) || time >= pending.expires || !system.contains(pending.key) {
            cancel(pending.id)
        }
    }
    func pendingIntent(_ id: UUID) -> FamilyCallWake? {
        refresh()
        guard let pending, pending.id == id else { return nil }
        return pending.intent
    }
    func pendingIncoming(peer: String, service: FamilySystemCallKey.Service) -> FamilySystemCallKey? {
        refresh()
        guard service == .reticulum, let pending, pending.voice == peer else { return nil }
        return pending.key
    }
    func attached(_ key: FamilySystemCallKey, to transport: FamilySystemCallKey) {
        guard let pending, pending.key == key, transport.service == .reticulum,
              system.contains(transport) else { return }
        self.pending = nil; deadline?.cancel(); deadline = nil
        status = "Approved call connected to its transport"
    }
    func cancel(_ id: UUID) {
        guard let pending, pending.id == id else { return }
        self.pending = nil; deadline?.cancel(); deadline = nil
        system.finish(pending.key, failed: true)
        status = "Call no longer available"
    }
    func close() { if let pending { cancel(pending.id) } }
}
