import AVFoundation
import Combine
import CoreLocation
import BackgroundTasks
import Network
import OSLog
import SwiftUI
import UIKit

@main
@MainActor
struct FamilyLiveApp: App {
    @UIApplicationDelegateAdaptor(FamilyNotifications.self) private var notifications
    @StateObject private var family = FamilyModel()
    @Environment(\.scenePhase) private var scenePhase

    private var keepScreenAwake: Bool {
        scenePhase == .active && family.state?.voice?.enabled == true && family.state?.voiceKeepAwake == true
    }

    var body: some Scene {
        WindowGroup {
            FamilyHome(family: family)
                .onChange(of: keepScreenAwake, initial: true) {
                    UIApplication.shared.isIdleTimerDisabled = keepScreenAwake
                }
                .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)
                    .receive(on: RunLoop.main)) { notification in
                    let rawReason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                    let reason = rawReason.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
                    if reason == .newDeviceAvailable || reason == .oldDeviceUnavailable {
                        family.reconnectVoiceAudio()
                    }
                }
                .task(id: scenePhase) {
                    family.notifications = notifications
                    notifications.openMessage = { [weak family = family] contactID, messageID in
                        family?.openNotification(contactID: contactID, messageID: messageID)
                    }
                    if scenePhase == .active {
                        await family.setVoicePresence(true)
                        await family.refreshNotificationPermission()
                        family.checkMailboxOnNextRefresh()
                    } else if scenePhase == .background {
                        await family.setVoicePresence(false)
                        await family.suspendLocation()
                        await family.lock()
                        family.scheduleMailboxRefresh()
                    }
                    while !Task.isCancelled && (scenePhase == .active || family.finishingSend) {
                        await family.refresh()
                        if scenePhase == .active {
                            await family.checkMailboxIfDue()
                            family.sampleLocationIfDue()
                        }
                        do { try await Task.sleep(for: .seconds(1)) }
                        catch { break }
                    }
                }
        }
        .backgroundTask(.appRefresh(FamilyModel.mailboxRefreshID)) {
            await family.refreshMailboxInBackground(notifications: notifications)
        }
    }
}

@MainActor
final class FamilyModel: ObservableObject {
    @Published private(set) var state: FamilyReply?
    @Published private(set) var unlocked = false
    @Published var error = ""
    @Published private(set) var notificationsAllowed = false
    @Published var notificationContactID: Int?
    @Published private(set) var speakerOn = false
    #if DEBUG
    @Published private(set) var testNotificationDelivered = false

    var testTCPRecovered: Bool {
        guard ProcessInfo.processInfo.environment["FAMILY_TEST_RECONNECT"] == "1",
              let epoch = state?.tcpSession?.split(separator: ":").last else { return false }
        return (Int(epoch) ?? 0) > 1
    }
    #endif
    weak var notifications: FamilyNotifications?
    private var sendTask: UIBackgroundTaskIdentifier = .invalid
    private var sendsStarting = 0
    private var guardianEpoch = 0
    private var pendingNotification: (Int, String)?
    private var nextMailboxCheck = ContinuousClock.now
    static let mailboxRefreshID = "org.meshchat.family.ios.live.mailbox"
    var finishingSend: Bool { sendTask != .invalid }

    private let client = FamilyClient()
    private let voiceAudio = FamilyVoiceAudio()
    private let voiceLogger = Logger(subsystem: "org.meshchat.family", category: "Reticulum call")
    @Published private(set) var voiceError = ""
    private var failingAudioCallID: String?
    private var lastVoiceCallID: String?
    private let locationSampler = FamilyLocationSampler()
    private let networkMonitor = NWPathMonitor()
    private var lastNetworkPath: NWPath?
    private var token = ""

    init() {
        networkMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in await self?.networkPathChanged(path) }
        }
        networkMonitor.start(queue: DispatchQueue(label: "family.network-path"))
    }

    private func networkPathChanged(_ path: NWPath) async {
        let previous = lastNetworkPath
        lastNetworkPath = path
        guard let previous, previous != path, path.status == .satisfied, state?.setupComplete == true else { return }
        _ = try? await request("tcp_network_changed")
    }

    func refresh() async {
        do {
            let updated = try await request("status")
            if let session = updated.tcpSession, session != state?.tcpSession {
                checkMailboxOnNextRefresh()
            }
            state = updated
            updateVoice(updated.voice)
            resolveNotification()
            if notificationsAllowed {
                await notifications?.publish(updated.messages ?? [:])
                #if DEBUG
                if !testNotificationDelivered &&
                    ProcessInfo.processInfo.environment["FAMILY_TEST_NOTIFICATIONS"] == "1" {
                    testNotificationDelivered = await notifications?.hasDeliveredMessage(from: messages) ?? false
                }
                #endif
            }
            finishSendIfIdle()
        } catch { self.error = error.localizedDescription }
    }

    func setVoicePresence(_ active: Bool) async {
        if !active {
            voiceAudio.stop()
            speakerOn = false
        }
        _ = try? await request("voice_presence", ["foreground": active])
    }

    func configureVoiceKeepAwake(_ enabled: Bool) async {
        _ = await perform("voice_keep_awake", ["token": token, "enabled": enabled])
    }

    func configureVoice(_ enabled: Bool) async {
        _ = await perform("voice_config", ["token": token, "enabled": enabled])
    }

    func call(_ contact: FamilyContact) async {
        guard await microphoneAllowed() else { return }
        voiceError = ""
        _ = await perform("voice_call", ["contactId": contact.id])
    }

    func answerCall() async {
        guard let voice = state?.voice, voice.call_state == "incoming", let id = voice.call_id,
              await microphoneAllowed() else { return }
        _ = await perform("voice_answer", ["callId": id])
    }

    func endCall() async {
        voiceAudio.stop()
        speakerOn = false
        guard let voice = state?.voice, voice.active, let id = voice.call_id else { return }
        _ = await perform("voice_hangup", ["callId": id])
    }

    var voiceCaptureStatus: String { voiceAudio.captureStatus }

    func reconnectVoiceAudio() {
        guard voiceAudio.callID != nil else { return }
        voiceAudio.stop()
        reconcileVoiceAudio(state?.voice)
    }

    func toggleSpeaker() {
        do {
            guard voiceAudio.callID != nil else { return }
            try voiceAudio.setSpeaker(!speakerOn)
            speakerOn = voiceAudio.usingBuiltInSpeaker
        } catch { self.error = error.localizedDescription }
    }

    private func microphoneAllowed() async -> Bool {
        let allowed = await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
        if !allowed { error = "Allow microphone access in iOS Settings to make or answer calls." }
        return allowed
    }

    private func updateVoice(_ voice: FamilyVoiceState?) {
        if let id = voice?.call_id, !id.isEmpty, id != lastVoiceCallID {
            lastVoiceCallID = id
            voiceError = ""
        }
        if let failure = voice?.error, !failure.isEmpty, failure != voiceError {
            voiceError = failure
            voiceLogger.error("Reticulum call failed: \(failure, privacy: .private)")
        }
        reconcileVoiceAudio(voice)
    }

    private func reconcileVoiceAudio(_ voice: FamilyVoiceState?) {
        guard UIApplication.shared.applicationState == .active,
              let voice, voice.call_state == "connected", let id = voice.call_id, !id.isEmpty else {
            if voiceAudio.callID != nil {
                voiceAudio.stop()
                speakerOn = false
            }
            return
        }
        guard failingAudioCallID != id else { return }
        do {
            if voiceAudio.callID == id {
                try voiceAudio.recoverStalledCapture()
            } else {
                try voiceAudio.start(callID: id)
            }
            speakerOn = voiceAudio.usingBuiltInSpeaker
        } catch {
            failingAudioCallID = id
            voiceError = "Call audio could not start. \(error.localizedDescription)"
            voiceLogger.error("Native call audio failed: \(error.localizedDescription, privacy: .private)")
            Task { _ = try? await request("voice_hangup", ["callId": id]) }
        }
    }

    func openNotification(contactID: Int, messageID: String) {
        pendingNotification = (contactID, messageID)
        resolveNotification()
    }

    private func resolveNotification() {
        guard let (contactID, messageID) = pendingNotification,
              let contacts = state?.contacts, let messages = state?.messages else { return }
        pendingNotification = nil
        guard contacts.contains(where: { $0.id == contactID }),
              messages[String(contactID)]?.contains(where: { $0.id == messageID && $0.incoming }) == true else { return }
        notificationContactID = contactID
    }

    private var messages: [FamilyMessage] {
        state?.messages?.values.flatMap { $0 } ?? []
    }

    func refreshNotificationPermission() async {
        notificationsAllowed = await notifications?.isAuthorized() ?? false
    }

    func enableNotifications() async {
        do {
            notificationsAllowed = try await notifications?.authorize(existingMessages: messages) ?? false
            error = notificationsAllowed ? "" : "Allow neXt Family notifications in iOS Settings."
        } catch { self.error = error.localizedDescription }
    }

    func saveMailbox(_ address: String) async -> Bool {
        let saved = await perform("mailbox_config", [
            "token": token, "address": address.trimmingCharacters(in: .whitespacesAndNewlines)
        ])
        if saved {
            nextMailboxCheck = .now
            scheduleMailboxRefresh()
        }
        return saved
    }

    func checkMailboxOnNextRefresh() {
        nextMailboxCheck = .now
    }

    func checkMailboxIfDue() async {
        guard mailboxEnabled, state?.tcpOnline == true, ContinuousClock.now >= nextMailboxCheck else { return }
        nextMailboxCheck = .now + .seconds(60)
        _ = try? await request("mailbox_sync")
    }

    private var mailboxEnabled: Bool {
        !(state?.mailbox?.address.isEmpty ?? true)
    }

    func scheduleMailboxRefresh() {
        let scheduler = BGTaskScheduler.shared
        if mailboxEnabled {
            let request = BGAppRefreshTaskRequest(identifier: Self.mailboxRefreshID)
            request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
            do { try scheduler.submit(request) }
            catch { NSLog("Family mailbox background refresh unavailable: %@", error.localizedDescription) }
        } else {
            scheduler.cancel(taskRequestWithIdentifier: Self.mailboxRefreshID)
        }
    }

    func refreshMailboxInBackground(notifications: FamilyNotifications) async {
        self.notifications = notifications
        await lock()
        await refreshNotificationPermission()
        let deadline = ContinuousClock.now + .seconds(22)
        var requested = false
        defer { if state != nil { scheduleMailboxRefresh() } }
        while !Task.isCancelled && ContinuousClock.now < deadline {
            await refresh()
            guard mailboxEnabled else { return }
            if requested {
                let status = state?.mailbox?.status
                if status == "complete" || status == "failed" { return }
            } else if state?.tcpOnline == true {
                if let status = try? await request("mailbox_sync").mailbox?.status {
                    requested = status == "syncing"
                    if status == "complete" || status == "failed" { return }
                }
            }
            do { try await Task.sleep(for: .seconds(1)) }
            catch { return }
        }
    }

    func send(contactID: Int, text: String, files: [FamilyDraftAttachment] = []) async -> Bool {
        sendsStarting += 1
        if !finishingSend {
            sendTask = UIApplication.shared.beginBackgroundTask(withName: "Finish Family message") { [weak self] in
                self?.endSendTask()
            }
        }
        defer {
            sendsStarting -= 1
            finishSendIfIdle()
        }
        var payload: [String: Any] = ["contactId": contactID, "text": text, "method": "auto"]
        if !files.isEmpty {
            payload["attachments"] = files.map { file -> [String: String] in
                var item = ["name": file.name, "data": file.data.base64EncodedString()]
                item["image"] = file.image
                return item
            }
        }
        return await perform("send", payload)
    }

    func attachmentURL(contactID: Int, messageID: String, index: Int) async throws -> URL {
        let reply = try await request("attachment_read", ["contactId": contactID, "messageId": messageID, "index": index])
        guard let path = reply.attachmentPath else { throw CocoaError(.fileNoSuchFile) }
        return URL(fileURLWithPath: path)
    }

    func setIncomingDeliveryLimit(_ bytes: Int) async -> Bool {
        await perform("incoming_delivery_limit", ["token": token, "bytes": bytes])
    }

    private func finishSendIfIdle() {
        let pending = messages.contains {
            !$0.incoming && ["Finding path", "Sending", "Sent · awaiting delivery proof"].contains($0.status)
        }
        if sendsStarting == 0 && !pending { endSendTask() }
    }

    private func endSendTask() {
        guard finishingSend else { return }
        let task = sendTask
        sendTask = .invalid
        UIApplication.shared.endBackgroundTask(task)
    }

    func perform(_ action: String, _ payload: [String: Any] = [:]) async -> Bool {
        do {
            let reply = try await request(action, payload)
            if reply.setupComplete != nil {
                state = reply
                updateVoice(reply.voice)
            }
            self.error = ""
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func unlock(_ password: String) async {
        let epoch = guardianEpoch
        do {
            let reply = try await request("unlock", ["password": password])
            let newToken = reply.token ?? ""
            guard epoch == guardianEpoch else {
                _ = try? await request("lock", ["token": newToken])
                return
            }
            token = newToken
            unlocked = !token.isEmpty
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    func lock() async {
        guardianEpoch += 1
        guard !token.isEmpty else { return }
        let current = token
        token = ""
        unlocked = false
        _ = try? await request("lock", ["token": current])
    }

    func savePeer(host: String, port: Int, enabled: Bool, backupHost: String, backupPort: Int) async {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test"), host == "rmap.world", enabled {
            guard await perform("device_name", ["token": token, "name": "Family iOS simulator test"]) else { return }
        }
        #endif
        _ = await perform("peer", ["token": token, "host": host, "port": port, "enabled": enabled,
                                   "backupHost": backupHost, "backupPort": backupPort])
    }

    func saveRNode(_ config: [String: Any]) async -> Bool {
        await perform("rnode", ["token": token, "config": config])
    }

    func saveDeviceName(_ name: String) async -> Bool {
        await perform("device_name", ["token": token, "name": name])
    }

    func readRoomCard(_ text: String) async -> FamilyRoomCard? {
        let epoch = guardianEpoch
        do {
            let result = try await request("qr_parse", ["token": token, "text": text, "target": "room"])
            guard epoch == guardianEpoch, unlocked else { return nil }
            guard let card = result.roomCard, card.service == "reticulum" else {
                error = "Choose a Reticulum Relay Chat room code."
                return nil
            }
            error = ""
            return card
        } catch {
            if epoch == guardianEpoch { self.error = error.localizedDescription }
            return nil
        }
    }

    func saveRoom(id: Int?, name: String, hub: String, channel: String,
                  readOnly: Bool, password: String, clearPassword: Bool) async -> Bool {
        var room: [String: Any] = ["name": name, "key": hub, "channel": channel,
                                    "service": "reticulum", "readOnly": readOnly]
        room["id"] = id
        return await perform("room_save", ["token": token, "room": room, "approved": true,
                                           "password": password, "clearPassword": clearPassword])
    }

    func discoverRooms(_ hub: String) async -> Bool {
        await perform("room_discover", ["token": token, "hubHash": hub, "service": "reticulum"])
    }

    func removeRoom(_ id: Int) async -> Bool {
        await perform("room_remove", ["token": token, "roomId": id])
    }

    func selectMap(_ id: String) async -> Bool {
        await perform("map_select", ["token": token, "mapId": id])
    }

    func removeMap(_ id: String) async -> Bool {
        await perform("map_remove", ["token": token, "mapId": id])
    }

    func mapTile(id: String, x: Int, y: Int, z: Int) async throws -> Data? {
        try await request("map_tile", ["mapId": id, "x": x, "y": y, "z": z]).tile
    }

    func importMap(_ source: URL) async -> Bool {
        let epoch = guardianEpoch
        do {
            let permit = try await request("map_import_prepare", ["token": token])
            guard let path = permit.mapImportPath else { return false }
            let destination = URL(fileURLWithPath: path)
            defer { try? FileManager.default.removeItem(at: destination) }
            try await Task.detached(priority: .utility) {
                let scoped = source.startAccessingSecurityScopedResource()
                defer { if scoped { source.stopAccessingSecurityScopedResource() } }
                let attributes = try source.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard attributes.isRegularFile == true,
                      let size = attributes.fileSize, (1...2_147_483_648).contains(size) else {
                    throw CocoaError(.fileReadTooLarge)
                }
                try FileManager.default.copyItem(at: source, to: destination)
            }.value
            guard epoch == guardianEpoch, unlocked else { return false }
            return await perform("map_import", ["token": token, "path": path,
                                                "name": source.deletingPathExtension().lastPathComponent])
        } catch {
            if epoch == guardianEpoch { self.error = error.localizedDescription }
            return false
        }
    }

    func saveLocationPolicy(mapEnabled: Bool, userControls: Bool, contactIDs: Set<Int>) async -> Bool {
        await perform("location_policy", [
            "token": token, "mapEnabled": mapEnabled, "userControls": userControls,
            "contactIds": contactIDs.sorted()
        ])
    }

    func startLocation(_ duration: String) async -> Bool {
        guard await perform("location_start", ["token": token, "duration": duration]) else { return false }
        locationSampler.requestPermission()
        return true
    }

    func stopLocation() async {
        if await perform("location_stop", ["token": token]) { locationSampler.suspend() }
    }

    func suspendLocation() async {
        locationSampler.suspend()
        _ = try? await request("location_suspend")
    }

    func sampleLocationIfDue() {
        guard state?.location?.active == true else { return }
        locationSampler.sampleIfDue { [weak self] fix in
            guard let self, UIApplication.shared.applicationState == .active,
                  self.state?.location?.active == true else { return }
            _ = try? await self.request("location_sample", ["fix": fix])
        }
    }

    func lookUpClient(_ address: String) async -> Bool {
        await perform("discover_client", ["token": token, "address": address])
    }

    func ownContactCard() async throws -> String? {
        let epoch = guardianEpoch
        let reply = try await request("contact_card", ["token": token])
        guard epoch == guardianEpoch, unlocked else { return nil }
        return reply.contactCardText
    }

    func readContactCard(_ text: String) async -> FamilyContactCard? {
        let epoch = guardianEpoch
        do {
            let result = try await request("qr_parse", ["token": token, "text": text, "target": "contact"])
            guard epoch == guardianEpoch, unlocked else { return nil }
            guard let card = result.card,
                  card.addresses["lxmf"]?.isEmpty == false || card.addresses["lxst"]?.isEmpty == false else {
                error = "Choose a contact code with a Reticulum messaging or calling address."
                return nil
            }
            error = ""
            return card
        } catch {
            if epoch == guardianEpoch { self.error = error.localizedDescription }
            return nil
        }
    }

    func resolveVoiceAddress(_ id: Int) async -> String? {
        do {
            return try await request("voice_resolve", ["token": token, "contactId": id]).address
        } catch {
            self.error = error.localizedDescription
            return nil
        }
    }

    func saveContact(id: Int? = nil, name: String, address: String, voiceAddress: String,
                     identityPublicKey: String? = nil) async -> Bool {
        let current = state?.contacts ?? []
        let lxmf = address.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let lxst = voiceAddress.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !lxmf.isEmpty || !lxst.isEmpty else {
            error = "Enter at least one approved Reticulum address."
            return false
        }
        guard [lxmf, lxst].allSatisfy({ $0.isEmpty || $0.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil }) else {
            error = "Reticulum addresses must contain 32 hexadecimal characters."
            return false
        }
        let previous = id.flatMap { id in current.first { $0.id == id } }
        if id != nil && previous == nil {
            error = "This contact is no longer approved."
            return false
        }
        var addresses = previous?.addresses ?? [:]
        let previousKey = addresses["lxmf"]?.lowercased() == lxmf ? previous?.identityPublicKey : nil
        addresses["lxmf"] = lxmf.isEmpty ? nil : lxmf
        addresses["lxst"] = lxst.isEmpty ? nil : lxst
        let contact = FamilyContact(
            id: id ?? (current.map(\.id).max() ?? 0) + 1,
            name: name.trimmingCharacters(in: .whitespacesAndNewlines), addresses: addresses,
            identityPublicKey: identityPublicKey ?? previousKey
        )
        var updated = current
        if let index = updated.firstIndex(where: { $0.id == contact.id }) { updated[index] = contact }
        else { updated.append(contact) }
        return await saveContacts(updated)
    }

    func removeContact(_ id: Int) async -> Bool {
        await saveContacts((state?.contacts ?? []).filter { $0.id != id })
    }

    private func saveContacts(_ contacts: [FamilyContact]) async -> Bool {
        let values = contacts.map { contact in
            var value: [String: Any] = ["id": contact.id, "name": contact.name, "addresses": contact.addresses]
            value["identityPublicKey"] = contact.identityPublicKey
            return value
        }
        return await perform("contacts", ["token": token, "contacts": values])
    }

    private func request(_ action: String, _ payload: [String: Any] = [:]) async throws -> FamilyReply {
        let data = try JSONSerialization.data(withJSONObject: ["action": action, "payload": payload])
        let result = try await client.request(String(decoding: data, as: UTF8.self))
        guard result.ok else {
            throw NSError(domain: "Family", code: 1, userInfo: [
                NSLocalizedDescriptionKey: result.error ?? "Family could not complete the request."
            ])
        }
        return result
    }
}

struct FamilyHome: View {
    @ObservedObject var family: FamilyModel
    @State private var password = ""
    @State private var confirmation = ""
    @State private var showGuardian = false
    @State private var guardianDismissingForCall = false
    @State private var notificationContact: FamilyContact?
    @State private var showNotificationChat = false
    @AppStorage("next-family-appearance") private var appearance = ""
    @Environment(\.colorScheme) private var systemAppearance

    private var night: Bool { appearance.isEmpty ? systemAppearance == .dark : appearance == "night" }

    var body: some View {
        NavigationStack {
            Form {
                if family.state?.setupComplete == false {
                    Section("Guardian setup") {
                        SecureField("Guardian password", text: $password)
                            .accessibilityIdentifier("setup-password")
                        SecureField("Confirm guardian password", text: $confirmation)
                            .accessibilityIdentifier("setup-confirmation")
                        NavigationLink("Review device permissions") { FamilyPermissionCheckup() }
                        Button("Create guardian access") {
                            Task {
                                if await family.perform("setup", [
                                    "password": password, "confirmation": confirmation, "reticulumEnabled": false
                                ]) {
                                    password = ""
                                    confirmation = ""
                                }
                            }
                        }
                    }
                } else if let state = family.state {
                    Section("Approved contacts") {
                        ForEach(state.contacts ?? []) { contact in
                            NavigationLink(contact.name) { FamilyChat(family: family, contact: contact) }
                        }
                    }
                    if let rooms = state.rooms, !rooms.isEmpty {
                        Section("Approved rooms") {
                            ForEach(rooms) { room in
                                NavigationLink(room.name) { FamilyRoomChat(family: family, room: room) }
                            }
                        }
                    }
                    Section("Connection") {
                        Text(state.tcpOnline == true ? "Reticulum TCP connected" : "Reticulum TCP offline")
                        if state.rnode?.enabled == true, let radio = state.rnodeRuntime {
                            Text(radio.online ? "Wi-Fi RNode connected" : radio.connecting ? "Connecting to RNode" : "Wi-Fi RNode offline")
                            if let battery = radio.battery {
                                let level = Int((battery.percent / 25).rounded()) * 25
                                Label("RNode battery: \(Int(battery.percent))%", systemImage: battery.state == "charging" ? "battery.100.bolt" : "battery.\(level)")
                            }
                        }
                        #if DEBUG
                        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test"), state.rrcIdentity != nil {
                            Text("Relay Chat ready").accessibilityIdentifier("relay-chat-ready")
                        }
                        #endif
                        if let mailbox = state.mailbox, !mailbox.address.isEmpty {
                            switch mailbox.status {
                            case "syncing": Text("Checking offline mailbox")
                            case "failed": Text("Couldn’t check offline mailbox")
                            case "complete": Text("Offline mailbox checked")
                            default: Text("Offline mailbox enabled")
                            }
                        }
                        if let address = state.address, !address.isEmpty {
                            Text(address).font(.caption.monospaced()).textSelection(.enabled)
                        }
                    }
                    if state.location?.mapEnabled == true {
                        Section {
                            NavigationLink("Family map") { FamilyLocationMap(family: family) }
                        }
                    }
                    if !family.notificationsAllowed {
                        Button("Enable message notifications") { Task { await family.enableNotifications() } }
                    }
                } else {
                    ProgressView("Starting Family")
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                if !family.voiceError.isEmpty { Text(family.voiceError).foregroundStyle(.red) }
            }
            .navigationTitle(family.state?.deviceName ?? "neXt Family")
            .preferredColorScheme(appearance.isEmpty ? nil : appearance == "night" ? .dark : .light)
            .toolbar {
                if family.state?.setupComplete == true {
                    ToolbarItem(placement: .topBarLeading) {
                        Button("Guardian settings", systemImage: "lock.shield") { showGuardian = true }
                            .labelStyle(.iconOnly)
                            .accessibilityIdentifier("guardian-settings")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(night ? "Day mode" : "Night mode", systemImage: night ? "sun.max" : "moon") {
                        appearance = night ? "day" : "night"
                    }
                    .accessibilityIdentifier("appearance-toggle")
                }
            }
            .navigationDestination(isPresented: $showNotificationChat) {
                if let contact = notificationContact {
                    FamilyChat(family: family, contact: contact).id(contact.id)
                }
            }
            .onChange(of: family.notificationContactID, initial: true) {
                guard let id = family.notificationContactID else { return }
                family.notificationContactID = nil
                guard let contact = family.state?.contacts?.first(where: { $0.id == id }) else { return }
                showGuardian = false
                notificationContact = contact
                showNotificationChat = true
            }
            .onChange(of: family.state?.voice?.active) {
                if family.state?.voice?.active == true && showGuardian {
                    guardianDismissingForCall = true
                    showGuardian = false
                }
            }
            .fullScreenCover(isPresented: Binding(
                get: { family.state?.voice?.active == true && !showGuardian && !guardianDismissingForCall },
                set: { _ in }
            )) {
                FamilyVoiceCall(family: family)
                    .interactiveDismissDisabled()
            }
            .sheet(isPresented: $showGuardian, onDismiss: {
                guardianDismissingForCall = false
                Task { await family.lock() }
            }) {
                FamilyGuardian(family: family)
            }
        }
    }
}

struct FamilyGuardian: View {
    @ObservedObject var family: FamilyModel
    @Environment(\.dismiss) private var dismiss
    @State private var password = ""
    @State private var host = "rmap.world"
    @State private var port = "4242"
    @State private var peerEnabled = false
    @State private var backupHost = ""
    @State private var backupPort = "4242"
    @FocusState private var editingDeviceName: Bool
    @State private var mailboxAddress = ""
    @State private var mailboxSaved = false
    @State private var deviceName = ""
    @State private var deviceNameSaved = false
    @State private var showPassword = false

    var body: some View {
        NavigationStack {
            Form {
                if family.unlocked {
                    NavigationLink("Permission checkup") { FamilyPermissionCheckup() }
                    Section("Approved contacts") {
                        NavigationLink("My contact QR") { FamilyOwnContactQR(family: family) }
                        NavigationLink("Add approved contact") { FamilyContactApproval(family: family) }
                        ForEach(family.state?.contacts ?? []) { contact in
                            NavigationLink(contact.name) { FamilyContactEditor(family: family, contact: contact) }
                        }
                    }
                    Section("Device name") {
                        TextField("Device name", text: $deviceName)
                            .accessibilityIdentifier("device-name")
                            .focused($editingDeviceName)
                        Button("Save device name") {
                            editingDeviceName = false
                            Task { deviceNameSaved = await family.saveDeviceName(deviceName) }
                        }
                        if deviceNameSaved { Text("Device name saved") }
                    }
                    Section("Reticulum TCP peer") {
                        Button(peerEnabled ? "Disable Reticulum TCP peer" : "Enable Reticulum TCP peer") {
                            peerEnabled.toggle()
                        }
                        .accessibilityIdentifier("peer-enabled")
                        TextField("Host", text: $host).textInputAutocapitalization(.never)
                            .accessibilityIdentifier("peer-host")
                        TextField("Port", text: $port).keyboardType(.numberPad)
                            .accessibilityIdentifier("peer-port")
                        Button("Save peer") {
                            Task {
                                await family.savePeer(host: host, port: Int(port) ?? 0, enabled: peerEnabled,
                                                      backupHost: backupHost, backupPort: Int(backupPort) ?? 0)
                            }
                        }
                        if family.state?.tcpOnline == true {
                            Text("Reticulum TCP connected").accessibilityIdentifier("guardian-peer-connected")
                        }
                        ForEach(family.state?.tcpConnections ?? [], id: \.endpoint) { connection in
                            LabeledContent(connection.endpoint, value: connection.online ? "Connected" : "Offline")
                        }
                        TextField("Backup hostname (optional)", text: $backupHost).textInputAutocapitalization(.never)
                        TextField("Backup port", text: $backupPort).keyboardType(.numberPad)
                        Text("With the RMAP preset, a blank backup hostname uses WashMesh and Chicagoland Mesh. Enter a hostname to use your own backup.")
                            .font(.footnote)
                    }
                    if family.state?.voiceSupported == true {
                        Section("Reticulum calling") {
                            Button(family.state?.voice?.enabled == true ? "Disable Reticulum calling" : "Enable Reticulum calling") {
                                Task { await family.configureVoice(family.state?.voice?.enabled != true) }
                            }
                            if family.state?.voice?.ready == true {
                                Text("Reticulum calling ready").accessibilityIdentifier("reticulum-voice-ready")
                                if family.state?.tcpOnline != true && family.state?.rnodeRuntime?.online != true {
                                    Text("Waiting for a Reticulum connection").font(.footnote)
                                }
                            }
                            Toggle("Keep screen awake for calls", isOn: Binding(
                                get: { family.state?.voiceKeepAwake == true },
                                set: { enabled in Task { await family.configureVoiceKeepAwake(enabled) } }
                            ))
                            .disabled(family.state?.voice?.enabled != true)
                            Text("Family receives calls while open. This option prevents auto-lock while you’re in Family. Locking the iPad or switching apps pauses incoming calls.")
                                .font(.footnote).foregroundStyle(.secondary)
                            if let address = family.state?.voice?.address, !address.isEmpty {
                                Text(address).font(.caption.monospaced()).textSelection(.enabled)
                            }
                            let incoming = family.state?.voice?.lastIncoming ?? ""
                            LabeledContent("Last incoming attempt", value: incoming.isEmpty ? "No incoming link recorded" : incoming)
                            if let error = family.state?.voice?.error, !error.isEmpty { Text(error).foregroundStyle(.red) }
                        }
                    }
                    Section {
                        NavigationLink("Wi-Fi RNode") { FamilyRNodeSettings(family: family) }
                        NavigationLink("Location sharing") { FamilyLocationSettings(family: family) }
                        NavigationLink("Incoming message size") { FamilyIncomingLimitSettings(family: family) }
                        NavigationLink("Offline maps") { FamilyOfflineMapSettings(family: family) }
                        NavigationLink("Approved rooms") { FamilyRoomSettings(family: family) }
                    }
                    Section("Offline message mailbox") {
                        TextField("LXMF propagation node address", text: $mailboxAddress)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button("Save mailbox") { Task { mailboxSaved = await family.saveMailbox(mailboxAddress) } }
                        if mailboxSaved { Text("Mailbox setting saved") }
                        Text("Leave blank to disable. Senders must use this mailbox for offline delivery.")
                            .font(.caption)
                    }
                } else {
                    Group {
                        if showPassword {
                            TextField("Guardian password", text: $password)
                                .accessibilityIdentifier("unlock-password")
                        } else {
                            SecureField("Guardian password", text: $password)
                                .accessibilityIdentifier("unlock-password")
                        }
                    }
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    Button(showPassword ? "Hide password" : "Show password") { showPassword.toggle() }
                    Button("Unlock") {
                        Task {
                            await family.unlock(password)
                            password = ""
                            showPassword = false
                        }
                    }
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
            .accessibilityIdentifier("guardian-settings-form")
            .navigationTitle("Guardian settings")
            .onChange(of: family.unlocked, initial: true) {
                if family.unlocked { loadSettings() }
            }
            .toolbar { Button("Done") { dismiss() } }
        }
    }
    private func loadSettings() {
        deviceName = family.state?.deviceName ?? "neXt Family"
        if let peer = family.state?.peer {
            host = peer.host
            port = String(peer.port)
            peerEnabled = peer.enabled
            backupHost = peer.backupHost ?? ""
            backupPort = String(peer.backupPort ?? 4242)
        }
        mailboxAddress = family.state?.mailbox?.address ?? ""
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test") {
            host = ProcessInfo.processInfo.environment["FAMILY_TEST_HOST"] ?? host
            port = ProcessInfo.processInfo.environment["FAMILY_TEST_PORT"] ?? port
        }
        #endif
    }

}

struct FamilyClientDiscovery: View {
    @ObservedObject var family: FamilyModel
    let select: (FamilyDiscoveredClient) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var search = ""
    @State private var requestedAddress: String?
    @State private var requesting = false

    private var query: String { search.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var lookup: FamilyClientLookup? { family.state?.clientLookup }
    private var approvedAddresses: Set<String> {
        Set((family.state?.contacts ?? []).compactMap { $0.addresses["lxmf"]?.lowercased() })
    }
    private var matches: [FamilyDiscoveredClient] {
        (family.state?.announces ?? []).filter { client in
            client.service == "lxmf" && !approvedAddresses.contains(client.address.lowercased()) &&
                (query.isEmpty || client.name.localizedCaseInsensitiveContains(query) ||
                    client.address.localizedCaseInsensitiveContains(query))
        }
    }

    var body: some View {
        Form {
            Section {
                TextField("Name or LXMF address", text: $search)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                if query.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil,
                   !approvedAddresses.contains(query.lowercased()), matches.isEmpty {
                    Button("Look up address") {
                        let address = query.lowercased()
                        requestedAddress = nil
                        requesting = true
                        Task {
                            if await family.lookUpClient(address) { requestedAddress = address }
                            requesting = false
                        }
                    }
                    .disabled(requesting || lookup?.pending == true || family.state?.tcpOnline != true)
                }
                if (requesting || requestedAddress == query.lowercased()),
                   let message = lookup?.message, !message.isEmpty {
                    Text(message).font(.caption)
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
            Section("Discovered clients") {
                if matches.isEmpty { Text("No matching clients") }
                ForEach(matches) { client in
                    Button {
                        select(client)
                        dismiss()
                    } label: {
                        VStack(alignment: .leading) {
                            Text(client.name)
                            Text(client.address).font(.caption.monospaced()).foregroundStyle(.secondary)
                        }
                    }
                    .accessibilityIdentifier("discovered-client-\(client.address)")
                }
            }
        }
        .navigationTitle("Find messaging client")
    }
}

struct FamilyChat: View {
    @ObservedObject var family: FamilyModel
    let contact: FamilyContact
    @State private var draft = ""
    @State private var submitting = false
    @State private var attachments: [FamilyDraftAttachment] = []
    @State private var confirmLargeSend = false

    private var currentContact: FamilyContact? {
        family.state?.contacts?.first { $0.id == contact.id }
    }

    private var canSend: Bool {
        currentContact?.addresses["lxmf"] == contact.addresses["lxmf"] && currentContact?.addresses["lxmf"]?.isEmpty == false
    }

    private func send() {
        let text = draft
        let photos = attachments.filter { $0.image != nil }
        let first = attachments.filter { $0.image == nil } + Array(photos.prefix(1))
        guard first.reduce(0, { $0 + $1.data.count }) <= FamilyDraftAttachment.limit else {
            family.error = "Send some attachments separately. Each Reticulum message allows up to 9.95 MB."
            return
        }
        let batches = [first] + photos.dropFirst().map { [$0] }
        submitting = true
        Task {
            defer { submitting = false }
            for (index, batch) in batches.enumerated() {
                guard await family.send(contactID: contact.id, text: index == 0 ? text : "", files: batch) else { return }
                if index == 0, draft == text { draft = "" }
                let sent = Set(batch.map(\.id))
                attachments.removeAll { sent.contains($0.id) }
            }
        }
    }

    var body: some View {
        Form {
            Section("Messages") {
                ForEach(family.state?.messages?[String(contact.id)] ?? []) { message in
                    VStack(alignment: .leading) {
                        if !message.text.isEmpty { Text(message.text) }
                        ForEach(Array(message.files.enumerated()), id: \.offset) { index, item in
                            FamilyReceivedAttachment(family: family, contactID: contact.id, messageID: message.id,
                                                     index: index, item: item)
                        }
                        if let error = message.attachmentError { Text(error).font(.caption) }
                        Text(message.status).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Section {
                TextField("Message", text: $draft).accessibilityIdentifier("message-draft")
                FamilyAttachmentComposer(attachments: $attachments)
                    .disabled(!canSend || submitting)
                Button("Send") {
                    if attachments.reduce(0, { $0 + $1.data.count }) > 900_000 { confirmLargeSend = true }
                    else { send() }
                }
                .disabled(!canSend || submitting || (draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && attachments.isEmpty))
                .confirmationDialog("This attachment may exceed the recipient’s limit", isPresented: $confirmLargeSend) {
                    Button("Send anyway") { send() }
                }
                if currentContact?.addresses["lxmf"] == nil { Text("This contact has no approved messaging address.") }
                else if !canSend { Text("Contact approval changed. Reopen this conversation.") }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                #if DEBUG
                if family.testNotificationDelivered { Text("Message notification delivered") }
                if family.testTCPRecovered { Text("Reticulum TCP reconnected") }
                #endif
            }
        }
        .navigationTitle(currentContact?.name ?? contact.name)
        .toolbar {
            if let currentContact, currentContact.addresses["lxst"]?.isEmpty == false,
               family.state?.voice?.ready == true {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Call", systemImage: "phone") { Task { await family.call(currentContact) } }
                }
            }
        }
    }
}
