import AVFoundation
import Combine
import Foundation
import Security
import UIKit
import Darwin

@MainActor
final class FamilySIP: ObservableObject {
    static let shared = FamilySIP()
    @Published private(set) var account: FamilySIPAccount?
    @Published private(set) var status = "SIP is off"
    @Published private(set) var phase = "idle"
    @Published private(set) var caller = ""
    @Published private(set) var error = ""
    @Published private(set) var muted = false
    @Published private(set) var speaker = UIDevice.current.userInterfaceIdiom == .pad
    private var contacts: [FamilyContact] = []
    private var running = false
    private var registered = false
    private var activeAccount: FamilySIPAccount?
    private var reticulumBusy = false
    private var incomingPeer = ""
    private var callID: String?
    private var nativeStarted = false
    private var activeDestination = ""
    private var interrupted = false
    private var systemKey: FamilySystemCallKey? { callID.map { FamilySystemCallKey(service: .sip, id: $0) } }
    private var retryAfter = Date.distantPast
    private var resolvedHosts = Set<String>()
    private var resolvedProvider = ""
    private var resolving = false
    private var resolveAfter = Date.distantPast
    var active: Bool { phase != "idle" }
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "org.meshchat.family.ios.sip",
         kSecAttrAccount as String: "account"]
    }

    var isRegistered: Bool { registered }

    private init() {
        var request = query
        request[kSecReturnData as String] = true
        var item: CFTypeRef?
        if SecItemCopyMatching(request as CFDictionary, &item) == errSecSuccess,
           let data = item as? Data {
            account = try? JSONDecoder().decode(FamilySIPAccount.self, from: data)
        }
    }

    func reconcile(_ state: FamilyReply) {
        contacts = state.contacts ?? []
        reticulumBusy = state.voice?.active == true
        if let id = callID, phase != "ending" {
            let stillApproved = incomingPeer.isEmpty
                ? contacts.contains { $0.addresses["sip"].flatMap { FamilySIPAddress($0)?.uri } == activeDestination }
                : approvedName(incomingPeer) != nil
            if !stillApproved { endDirect(id) }
        }
        if state.setupComplete == true && account?.enabled == true && !running && Date() >= retryAfter { start() }
        if let host = account?.host, !resolving && (resolvedProvider != host || Date() >= resolveAfter) {
            resolving = true
            resolvedHosts = resolvedProvider == host ? resolvedHosts : []
            Task {
                let addresses = await Task.detached { Self.resolve(host) }.value
                if account?.host == host {
                    resolvedProvider = host
                    resolvedHosts = addresses
                    resolveAfter = Date().addingTimeInterval(60)
                }
                resolving = false
            }
        }
    }

    func save(_ value: FamilySIPAccount) -> Bool {
        guard FamilySIPAddress("sip:\(value.user)@\(value.host):\(value.port)") != nil,
              !value.password.isEmpty, value.password.utf8.count <= 256 else {
            error = "Enter the account, provider hostname, port and password."
            return false
        }
        guard let data = try? JSONEncoder().encode(value) else { return false }
        let changed = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if changed == errSecItemNotFound {
            var item = query
            item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else {
                error = "Family could not save the SIP account in Keychain."
                return false
            }
        } else if changed != errSecSuccess {
            error = "Family could not update the SIP account in Keychain."
            return false
        }
        account = value
        registered = false
        error = ""
        if running { family_sip_command(9, nil) }
        else if value.enabled { start() }
        else { status = "SIP is off" }
        return true
    }

    private func start() {
        guard !running, let account, account.enabled else { return }
        running = true
        activeAccount = account
        status = "Connecting SIP"
        DispatchQueue.global(qos: .userInitiated).async {
            account.user.withCString { user in
                account.host.withCString { host in
                    account.password.withCString { password in
                        _ = family_sip_run(user, host, Int32(account.port), password) { state, peer, code, nativeID in
                            let name = state.map { String(cString: $0) } ?? "engine_failed"
                            let address = peer.map { String(cString: $0) } ?? ""
                            let id = nativeID.map { String(cString: $0) } ?? ""
                            Task { @MainActor in FamilySIP.shared.receive(name, peer: address, code: code, nativeID: id) }
                        }
                    }
                }
            }
        }
    }

    func networkChanged() {
        resolveAfter = .distantPast
        if running && !active { family_sip_command(9, nil) }
    }

    func call(_ contact: FamilyContact) async {
        guard registered, !active, !reticulumBusy,
              let approved = contacts.first(where: { $0.id == contact.id }),
              let raw = approved.addresses["sip"], let destination = FamilySIPAddress(raw),
              await microphoneAllowed() else {
            error = "Connect SIP and approve this contact’s SIP address before calling."
            return
        }
        let id = UUID().uuidString
        callID = id
        nativeStarted = false
        activeDestination = destination.uri
        caller = approved.name
        phase = "calling"
        error = ""
        if FamilySystemCalls.shared.enabled {
            if !FamilySystemCalls.shared.track(FamilySystemCallKey(service: .sip, id: id), name: caller,
                incoming: false, actions: systemActions(id, destination: destination.uri)) { finishCall() }
        } else {
            guard await prepareAudio(), startDirect(id, destination: destination.uri) else {
                if callID == id { finishCall(failed: true) }
                return
            }
        }
    }

    func answer() async {
        guard let id = callID, phase == "incoming" else { return }
        if let key = systemKey, FamilySystemCalls.shared.owns(key) {
            await FamilySystemCalls.shared.requestAnswer(key)
        } else if await prepareAudio() { _ = answerDirect(id) }
    }

    func end() {
        guard let id = callID else { return }
        if let key = systemKey, FamilySystemCalls.shared.owns(key) {
            Task { await FamilySystemCalls.shared.requestEnd(key) }
        } else { endDirect(id) }
    }

    func toggleMute() {
        guard let id = callID else { return }
        let value = !muted
        if let key = systemKey, FamilySystemCalls.shared.owns(key) {
            Task { await FamilySystemCalls.shared.requestMute(key, muted: value) }
        } else { _ = setMuted(value, id: id) }
    }

    private func command(_ operation: Int32, _ value: String? = nil, id: String) -> Bool {
        guard callID == id else { return false }
        return id.withCString { callID in
            if let value { return value.withCString { family_sip_call_command(operation, $0, callID) == 0 } }
            return family_sip_call_command(operation, nil, callID) == 0
        }
    }

    private func systemActions(_ id: String, destination: String? = nil) -> FamilySystemCallActions {
        FamilySystemCallActions(
            prepareAudio: { [weak self] in
                guard let self, self.callID == id else { return false }
                return await self.prepareAudio()
            },
            start: { [weak self] in
                guard let destination else { return false }
                return self?.startDirect(id, destination: destination) ?? false
            },
            answer: { [weak self] in self?.answerDirect(id) ?? false },
            end: { [weak self] in self?.endDirect(id) },
            mute: { [weak self] muted in self?.setMuted(muted, id: id) ?? false }
        )
    }

    private func startDirect(_ id: String, destination: String) -> Bool {
        guard callID == id, phase == "calling", registered, !reticulumBusy,
              contacts.contains(where: { $0.addresses["sip"].flatMap { FamilySIPAddress($0)?.uri } == destination }),
              command(1, destination, id: id) else { return false }
        nativeStarted = true
        if muted { _ = command(4, "1", id: id) }
        return true
    }

    private func answerDirect(_ id: String) -> Bool {
        guard callID == id, phase == "incoming", !reticulumBusy, approvedName(incomingPeer) != nil else { return false }
        return command(2, id: id)
    }

    private func endDirect(_ id: String) {
        guard callID == id else { return }
        if nativeStarted {
            phase = "ending"
            if !command(3, id: id) { finishCall() }
        } else { finishCall() }
    }

    private func setMuted(_ value: Bool, id: String) -> Bool {
        guard callID == id, active, phase != "ending" else { return false }
        if nativeStarted && !command(4, value ? "1" : "0", id: id) { return false }
        muted = value
        return true
    }

    func toggleSpeaker() {
        guard !FamilyCallAudioSession.hasExternalOutput else { return }
        let next = !speaker
        do {
            try AVAudioSession.sharedInstance().overrideOutputAudioPort(next ? .speaker : .none)
            speaker = next
        } catch { self.error = error.localizedDescription }
    }

    private func microphoneAllowed() async -> Bool {
        let allowed: Bool = await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
        if !allowed { error = "Allow microphone access in Family’s device settings to make calls." }
        return allowed
    }

    private func prepareAudio() async -> Bool {
        guard await microphoneAllowed() else { return false }
        do {
            try FamilyCallAudioSession.configure()
            if systemKey.map({ FamilySystemCalls.shared.owns($0) }) != true {
                try AVAudioSession.sharedInstance().setActive(true)
            }
            return true
        } catch { self.error = error.localizedDescription; return false }
    }

    func setForeground(_ active: Bool) {
        if !active, phase != "connected", let id = callID,
           systemKey.map({ FamilySystemCalls.shared.contains($0) }) != true { endDirect(id) }
    }

    func systemAudioChanged() {
        guard let key = systemKey, FamilySystemCalls.shared.owns(key), phase == "connected" else { return }
        interrupted = !FamilySystemCalls.shared.allowsAudio(key)
        if interrupted { _ = command(8, id: key.id) }
        else {
            _ = command(7, id: key.id)
            _ = command(4, muted ? "1" : "0", id: key.id)
        }
    }

    func interruptionBegan() {
        interrupted = true
        if let id = callID, phase == "connected" { _ = command(8, id: id) }
    }

    func interruptionEnded(shouldResume: Bool) async {
        guard let id = callID, phase == "connected" else { return }
        if let key = systemKey, FamilySystemCalls.shared.owns(key) { systemAudioChanged(); return }
        guard shouldResume else { endDirect(id); return }
        if await prepareAudio(), callID == id {
            interrupted = false
            _ = command(7, id: id)
            _ = command(4, muted ? "1" : "0", id: id)
        }
    }

    func routeChanged() {
        speaker = AVAudioSession.sharedInstance().currentRoute.outputs.contains { $0.portType == .builtInSpeaker }
        guard let id = callID, phase == "connected", !interrupted,
              systemKey.map({ FamilySystemCalls.shared.allowsAudio($0) }) != false else { return }
        _ = command(7, id: id)
        _ = command(4, muted ? "1" : "0", id: id)
    }

    func mediaServicesReset() {
        if active { error = "Audio services restarted. Please call again." }
        family_sip_command(9, nil)
    }

    private func approvedName(_ raw: String) -> String? {
        guard let incoming = FamilySIPAddress(raw) else { return nil }
        let matches = contacts.filter { contact in
            guard let raw = contact.addresses["sip"], let approved = FamilySIPAddress(raw) else { return false }
            return approved.matches(incoming, providerHost: account?.host ?? "", providerPort: account?.port ?? 0, resolvedHosts: resolvedHosts)
        }
        return matches.count == 1 ? matches[0].name : nil
    }

    private func receive(_ state: String, peer: String, code: Int32, nativeID: String) {
        switch state {
        case "ready":
            if account?.enabled != true || account != activeAccount { family_sip_command(9, nil) }
        case "registering": status = "Registering SIP"
        case "registered": registered = true; status = "SIP connected"
        case "registration_failed": registered = false; status = "SIP registration failed (\(code))"
        case "incoming":
            guard !nativeID.isEmpty else { return }
            guard !reticulumBusy, !active, let name = approvedName(peer) else {
                nativeID.withCString { _ = family_sip_call_command(3, nil, $0) }
                return
            }
            callID = nativeID
            nativeStarted = true
            caller = name
            incomingPeer = peer
            phase = "incoming"
            error = ""
            if FamilySystemCalls.shared.enabled,
               !FamilySystemCalls.shared.track(FamilySystemCallKey(service: .sip, id: nativeID), name: name,
                incoming: true, actions: systemActions(nativeID)) { endDirect(nativeID) }
        case "calling", "ringing", "progress", "connected":
            guard callID == nativeID else { return }
            phase = state
            if let key = systemKey { FamilySystemCalls.shared.update(key, connected: state == "connected") }
        case "muted":
            if callID == nativeID { muted = code != 0 }
        case "ended":
            if callID == nativeID { finishCall() }
        case "audio_error":
            guard callID == nativeID, let id = callID else { return }
            error = "SIP audio could not start (\(code))"
            endDirect(id)
        case "command_failed":
            guard callID == nativeID else { return }
            error = "SIP command failed (\(code))"
            if phase == "calling" || phase == "ending" { finishCall(failed: true) }
        case "engine_failed": error = "SIP could not start (\(code))"
        case "stopped":
            running = false
            activeAccount = nil
            retryAfter = Date().addingTimeInterval(code == 0 ? 0 : 15)
            registered = false
            finishCall(failed: code != 0)
            status = "SIP disconnected"
            if account?.enabled == true && code == 0 { start() }
        default: break
        }
    }

    private func finishCall(failed: Bool = false) {
        let key = systemKey
        let managed = key.map { FamilySystemCalls.shared.owns($0) } ?? false
        callID = nil
        nativeStarted = false
        activeDestination = ""
        interrupted = false
        phase = "idle"
        caller = ""
        incomingPeer = ""
        muted = false
        if let key { FamilySystemCalls.shared.finish(key, failed: failed) }
        if !reticulumBusy && !managed {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    nonisolated private static func resolve(_ host: String) -> Set<String> {
        var result: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, nil, nil, &result) == 0 else { return [] }
        defer { if let result { freeaddrinfo(result) } }
        var current = result
        var addresses = Set<String>()
        while let record = current {
            var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(record.pointee.ai_addr, record.pointee.ai_addrlen, &buffer, socklen_t(buffer.count), nil, 0, NI_NUMERICHOST) == 0 {
                addresses.insert(String(cString: buffer))
            }
            current = record.pointee.ai_next
        }
        return addresses
    }
}
