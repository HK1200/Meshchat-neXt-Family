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
    private var reticulumBusy = false
    private var incomingPeer = ""
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
        status = "Connecting SIP"
        DispatchQueue.global(qos: .userInitiated).async {
            account.user.withCString { user in
                account.host.withCString { host in
                    account.password.withCString { password in
                        _ = family_sip_run(user, host, Int32(account.port), password) { state, peer, code in
                            let name = state.map { String(cString: $0) } ?? "engine_failed"
                            let address = peer.map { String(cString: $0) } ?? ""
                            Task { @MainActor in FamilySIP.shared.receive(name, peer: address, code: code) }
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
        guard await microphoneAllowed(), registered, !active, !reticulumBusy,
              let approved = contacts.first(where: { $0.id == contact.id }),
              let raw = approved.addresses["sip"],
              let destination = FamilySIPAddress(raw) else {
            error = "Connect SIP and approve this contact’s SIP address before calling."
            return
        }
        do { try activateAudio() } catch { self.error = error.localizedDescription; return }
        caller = approved.name
        phase = "calling"
        destination.uri.withCString { family_sip_command(1, $0) }
    }

    func answer() async {
        guard await microphoneAllowed(), phase == "incoming", !reticulumBusy, approvedName(incomingPeer) != nil else { return }
        do { try activateAudio() } catch { self.error = error.localizedDescription; return }
        family_sip_command(2, nil)
    }

    func end() { family_sip_command(3, nil) }
    func toggleMute() {
        muted.toggle()
        (muted ? "1" : "0").withCString { family_sip_command(4, $0) }
    }
    func toggleSpeaker() {
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

    private func activateAudio() throws {
        let audio = AVAudioSession.sharedInstance()
        let options: AVAudioSession.CategoryOptions = UIDevice.current.userInterfaceIdiom == .pad ? [.defaultToSpeaker, .allowBluetooth] : [.allowBluetooth]
        try audio.setCategory(.playAndRecord, mode: .voiceChat, options: options)
        try audio.setActive(true)
    }

    private func approvedName(_ raw: String) -> String? {
        guard let incoming = FamilySIPAddress(raw) else { return nil }
        let matches = contacts.filter { contact in
            guard let raw = contact.addresses["sip"], let approved = FamilySIPAddress(raw) else { return false }
            return approved.matches(incoming, providerHost: account?.host ?? "", providerPort: account?.port ?? 0, resolvedHosts: resolvedHosts)
        }
        return matches.count == 1 ? matches[0].name : nil
    }

    private func receive(_ state: String, peer: String, code: Int32) {
        switch state {
        case "ready":
            if account?.enabled != true { family_sip_command(9, nil) }
        case "registering": status = "Registering SIP"
        case "registered": registered = true; status = "SIP connected"
        case "registration_failed": registered = false; status = "SIP registration failed (\(code))"
        case "incoming":
            guard !reticulumBusy, let name = approvedName(peer) else { family_sip_command(3, nil); return }
            caller = name
            incomingPeer = peer
            phase = "incoming"
        case "calling", "ringing", "progress", "connected": phase = state
        case "ended": finishCall()
        case "audio_error":
            error = "SIP audio could not start (\(code))"
            family_sip_command(3, nil)
        case "command_failed":
            error = "SIP command failed (\(code))"
            if phase == "calling" { finishCall() }
        case "engine_failed": error = "SIP could not start (\(code))"
        case "stopped":
            running = false
            retryAfter = Date().addingTimeInterval(code == 0 ? 0 : 15)
            registered = false
            finishCall()
            status = "SIP disconnected"
            // A saved account change restarts only after the previous engine exits.
            if account?.enabled == true && code == 0 { start() }
        default: break
        }
    }

    private func finishCall() {
        phase = "idle"
        caller = ""
        incomingPeer = ""
        muted = false
        if !reticulumBusy { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
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
