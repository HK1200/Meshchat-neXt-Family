import Combine
import Foundation

struct FamilySystemCallKey: Hashable, Sendable {
    enum Service: String, Sendable { case reticulum, sip }
    let service: Service
    let id: String
}

@MainActor
struct FamilySystemCallActions {
    let prepareAudio: () async -> Bool
    let start: () async -> Bool
    let answer: () async -> Bool
    let end: () async -> Void
    let mute: (Bool) async -> Bool
}

@MainActor
protocol FamilySystemCallEvents: AnyObject {
    func systemStart(_ id: UUID) async -> Bool
    func systemAnswer(_ id: UUID) async -> Bool
    func systemEnd(_ id: UUID) async -> Bool
    func systemMute(_ id: UUID, muted: Bool) async -> Bool
    func systemAudioActivated()
    func systemAudioDeactivated()
    func systemReset()
    func systemActionTimedOut(_ id: UUID)
}

@MainActor
protocol FamilySystemCallDriver: AnyObject {
    var events: (any FamilySystemCallEvents)? { get set }
    func incoming(_ id: UUID, name: String) async throws
    func start(_ id: UUID, name: String) async throws
    func answer(_ id: UUID) async throws
    func end(_ id: UUID) async throws
    func mute(_ id: UUID, muted: Bool) async throws
    func connected(_ id: UUID)
    func ended(_ id: UUID, failed: Bool)
}

/// Keeps CallKit actions bound to one approved transport call, including across awaits.
@MainActor
final class FamilySystemCalls: ObservableObject, FamilySystemCallEvents {
    static let shared = FamilySystemCalls(driver: FamilyCallKitDriver())
    @Published private(set) var audioReady = false
    @Published private(set) var enabled: Bool
    @Published private(set) var error = ""
    private let driver: any FamilySystemCallDriver
    private let preferences: UserDefaults?
    private static let preferenceKey = "family.systemCallControls"
    private var entry: Entry?
    private var incomingAttempts: [UUID: IncomingAttempt] = [:]
    private final class IncomingAttempt {
        var result: Bool?
        var waiters: [CheckedContinuation<Bool, Never>] = []
        func finish(_ success: Bool) {
            guard result == nil else { return }
            result = success
            let pending = waiters; waiters.removeAll()
            for continuation in pending { continuation.resume(returning: success) }
        }
        func wait() async -> Bool {
            if let result { return result }
            return await withCheckedContinuation { waiters.append($0) }
        }
    }

    private final class Entry {
        let id: UUID
        var key: FamilySystemCallKey
        let incoming: Bool
        var actions: FamilySystemCallActions
        var awaitingTransport: Bool
        var transportWaiter: CheckedContinuation<Bool, Never>?
        var reportResult: Bool?
        var reportWaiters: [CheckedContinuation<Bool, Never>] = []
        var connected = false
        var answered = false
        var ending = false
        var answerPending = false
        var startPending = false
        var preparing = false
        var starting = false
        var started = false
        var reportedConnected = false
        init(key: FamilySystemCallKey, incoming: Bool, actions: FamilySystemCallActions, systemID: UUID? = nil) {
            self.id = systemID ?? UUID()
            self.key = key; self.incoming = incoming; self.actions = actions
            self.awaitingTransport = systemID != nil
        }
        func resolveTransport(_ ready: Bool) {
            let waiter = transportWaiter; transportWaiter = nil
            waiter?.resume(returning: ready)
        }
        func resolveReport(_ accepted: Bool) {
            guard reportResult == nil else { return }
            reportResult = accepted
            let waiters = reportWaiters; reportWaiters.removeAll()
            for waiter in waiters { waiter.resume(returning: accepted) }
        }
    }

    init(driver: any FamilySystemCallDriver, preferences: UserDefaults? = .standard, enabled: Bool? = nil) {
        self.driver = driver
        self.preferences = preferences
        self.enabled = enabled ?? (preferences?.object(forKey: Self.preferenceKey) as? Bool ?? true)
        driver.events = self
    }

    @discardableResult
    func setEnabled(_ enabled: Bool) -> Bool {
        guard entry == nil else { error = "End the current call before changing call controls."; return false }
        self.enabled = enabled
        preferences?.set(enabled, forKey: Self.preferenceKey)
        error = ""
        return true
    }

    func owns(_ key: FamilySystemCallKey) -> Bool { entry?.key == key }
    func contains(_ key: FamilySystemCallKey) -> Bool { entry?.key == key && entry?.ending == false }
    func allowsAudio(_ key: FamilySystemCallKey) -> Bool { !enabled || (contains(key) && audioReady) }
    var hasCall: Bool { entry != nil }

    @discardableResult
    func track(_ key: FamilySystemCallKey, name: String, incoming: Bool, actions: FamilySystemCallActions) -> Bool {
        report(key, name: name, incoming: incoming, actions: actions, systemID: nil)
    }

    /// Reserve the authenticated wake UUID before its transport has reconnected.
    /// The caller must cancel an expired/revoked wake through finish or systemEnd.
    @discardableResult
    func reserveIncoming(_ key: FamilySystemCallKey, id: UUID, name: String,
                         actions: FamilySystemCallActions) -> Bool {
        guard enabled else { return false }
        return report(key, name: name, incoming: true, actions: actions, systemID: id)
    }

    /// A required VoIP push must not complete before the real CallKit report.
    /// UUID lookup also survives an earlier authenticated transport adoption.
    func incomingReportCompleted(_ id: UUID) async -> Bool {
        guard let entry, entry.id == id, entry.incoming, !entry.ending else { return false }
        if let result = entry.reportResult { return result }
        return await withCheckedContinuation { entry.reportWaiters.append($0) }
    }

    /// Unlike call-liveness waiters, an OS push completion must wait for the
    /// actual report callback even when the call is cancelled in the meantime.
    func incomingAttemptCompleted(_ id: UUID) async -> Bool {
        guard let attempt = incomingAttempts[id] else { return false }
        return await attempt.wait()
    }

    /// PushKit can require a CallKit report even after consent was revoked or
    /// the signed intent became unusable. Report then end a fresh generic UUID;
    /// never borrow, answer or finish the real call currently owned by entry.
    /// This path does not authorize signaling, start audio or change settings.
    func reportUnusableWake() async {
        let id = UUID()
        do { try await driver.incoming(id, name: "Unavailable call") }
        catch { return }
        driver.ended(id, failed: true)
    }

    /// Adopt one authenticated arriving call without reporting a second CallKit call.
    @discardableResult
    func attachIncoming(_ pending: FamilySystemCallKey, to key: FamilySystemCallKey,
                        actions: FamilySystemCallActions) -> Bool {
        guard let entry, entry.key == pending, entry.incoming, entry.awaitingTransport,
              pending.service == key.service, !entry.ending, !entry.connected,
              !entry.starting, !entry.started, !entry.answered else { return false }
        entry.key = key; entry.actions = actions; entry.awaitingTransport = false
        entry.resolveTransport(true)
        return true
    }

    private func report(_ key: FamilySystemCallKey, name: String, incoming: Bool,
                        actions: FamilySystemCallActions, systemID: UUID?) -> Bool {
        guard enabled else { return true }
        if let entry {
            return entry.key == key && !entry.ending && (systemID == nil || systemID == entry.id)
        }
        let value = Entry(key: key, incoming: incoming, actions: actions, systemID: systemID)
        let attempt: IncomingAttempt?
        if incoming, systemID != nil {
            incomingAttempts = incomingAttempts.filter { $0.value.result == nil }
            guard incomingAttempts.count < 32 else { return false }
            let receipt = IncomingAttempt()
            incomingAttempts[value.id] = receipt
            attempt = receipt
        } else { attempt = nil }
        entry = value
        audioReady = false
        error = ""
        Task {
            // A required wake report cannot disappear if cancellation wins
            // before this queued task runs. It is still reported, then ended.
            guard attempt != nil || (self.entry === value && !value.ending) else { return }
            do {
                if incoming { try await driver.incoming(value.id, name: name) }
                else { try await driver.start(value.id, name: name) }
                attempt?.finish(true)
                if self.entry !== value || value.ending {
                    value.resolveReport(false)
                    driver.ended(value.id, failed: false)
                } else { value.resolveReport(true) }
            } catch {
                attempt?.finish(false)
                value.resolveReport(false)
                guard self.entry === value else { return }
                self.error = "iOS could not show this call. Please try again."
                await fail(value)
            }
        }
        return true
    }

    func update(_ key: FamilySystemCallKey, connected: Bool) {
        guard let entry, entry.key == key, !entry.ending, connected, !entry.connected else { return }
        entry.connected = true
        if !entry.incoming && entry.started && !entry.reportedConnected {
            entry.reportedConnected = true
            driver.connected(entry.id)
        }
    }

    func finish(_ key: FamilySystemCallKey, failed: Bool = false) {
        guard let entry, entry.key == key else { return }
        self.entry = nil
        entry.resolveTransport(false)
        entry.resolveReport(false)
        audioReady = false
        driver.ended(entry.id, failed: failed)
    }

    func requestAnswer(_ key: FamilySystemCallKey) async {
        guard let entry, entry.key == key, !entry.ending else { return }
        do { try await driver.answer(entry.id) }
        catch { if self.entry === entry { self.error = "iOS could not answer this call."; await fail(entry) } }
    }

    func requestEnd(_ key: FamilySystemCallKey) async {
        guard let entry, entry.key == key, !entry.ending else { return }
        do { try await driver.end(entry.id) }
        catch { if self.entry === entry { await fail(entry) } }
    }

    func requestMute(_ key: FamilySystemCallKey, muted: Bool) async {
        guard let entry, entry.key == key, !entry.ending else { return }
        do { try await driver.mute(entry.id, muted: muted) }
        catch { if self.entry === entry { self.error = "iOS could not change the microphone setting." } }
    }

    func systemStart(_ id: UUID) async -> Bool {
        guard let entry, entry.id == id, !entry.incoming, !entry.ending,
              !entry.preparing, !entry.starting, !entry.startPending, !entry.started else { return false }
        entry.preparing = true
        let prepared = await entry.actions.prepareAudio()
        guard self.entry === entry, !entry.ending else { return false }
        entry.preparing = false
        guard prepared else { await fail(entry); return false }
        entry.startPending = true
        runPending()
        return true
    }

    func systemAnswer(_ id: UUID) async -> Bool {
        guard let entry, entry.id == id, entry.incoming, !entry.ending, !entry.connected,
              !entry.preparing, !entry.starting, !entry.answerPending, !entry.answered else { return false }
        entry.preparing = true
        if entry.awaitingTransport {
            let attached = await withCheckedContinuation { entry.transportWaiter = $0 }
            guard attached, self.entry === entry, !entry.ending else { return false }
        }
        let prepared = await entry.actions.prepareAudio()
        guard self.entry === entry, !entry.ending else { return false }
        entry.preparing = false
        guard prepared else { await fail(entry); return false }
        entry.answerPending = true
        runPending()
        return true
    }

    func systemEnd(_ id: UUID) async -> Bool {
        guard let entry, entry.id == id, !entry.ending else { return false }
        entry.ending = true
        entry.resolveTransport(false)
        entry.resolveReport(false)
        audioReady = false
        await entry.actions.end()
        if self.entry === entry { finish(entry.key) }
        return true
    }

    func systemMute(_ id: UUID, muted: Bool) async -> Bool {
        guard let entry, entry.id == id, !entry.ending else { return false }
        let result = await entry.actions.mute(muted)
        return result && self.entry === entry && !entry.ending
    }

    func systemAudioActivated() { audioReady = entry != nil && entry?.ending == false; runPending() }
    func systemAudioDeactivated() { audioReady = false }

    func systemReset() {
        guard let entry else { audioReady = false; return }
        Task { await fail(entry) }
    }

    func systemActionTimedOut(_ id: UUID) {
        guard let entry, entry.id == id else { return }
        error = "The system call action timed out. Please call again."
        Task { await fail(entry) }
    }

    private func runPending() {
        guard let entry, audioReady, !entry.ending, !entry.starting,
              entry.answerPending || entry.startPending else { return }
        let answer = entry.answerPending
        entry.answerPending = false
        entry.startPending = false
        entry.starting = true
        Task {
            guard self.entry === entry, !entry.ending else { return }
            guard self.audioReady else {
                entry.starting = false
                if answer { entry.answerPending = true } else { entry.startPending = true }
                return
            }
            let result: Bool
            if answer { result = await entry.actions.answer() }
            else { result = await entry.actions.start() }
            guard self.entry === entry else { return }
            entry.starting = false
            if !result { await fail(entry) }
            else if answer { entry.answered = true }
            else {
                entry.started = true
                if entry.connected && !entry.incoming && !entry.reportedConnected {
                    entry.reportedConnected = true
                    driver.connected(entry.id)
                }
            }
        }
    }

    private func fail(_ value: Entry) async {
        guard entry === value, !value.ending else { return }
        value.ending = true
        value.resolveTransport(false)
        value.resolveReport(false)
        audioReady = false
        await value.actions.end()
        if entry === value { finish(value.key, failed: true) }
    }
}
