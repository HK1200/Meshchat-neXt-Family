import BackgroundTasks
import Network
import SwiftUI
import UIKit

@main
@MainActor
struct FamilyLiveApp: App {
    @UIApplicationDelegateAdaptor(FamilyNotifications.self) private var notifications
    @StateObject private var family = FamilyModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            FamilyHome(family: family)
                .task(id: scenePhase) {
                    family.notifications = notifications
                    if scenePhase == .active {
                        await family.refreshNotificationPermission()
                        family.checkMailboxOnNextRefresh()
                    } else {
                        await family.lock()
                        if scenePhase == .background { family.scheduleMailboxRefresh() }
                    }
                    while !Task.isCancelled && (scenePhase == .active || family.finishingSend) {
                        await family.refresh()
                        if scenePhase == .active { await family.checkMailboxIfDue() }
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
    private var nextMailboxCheck = ContinuousClock.now
    static let mailboxRefreshID = "org.meshchat.family.ios.live.mailbox"
    var finishingSend: Bool { sendTask != .invalid }

    private let client = FamilyClient()
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
            if notificationsAllowed {
                await notifications?.publish(messages)
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

    func send(contactID: Int, text: String) async -> Bool {
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
        return await perform("send", ["contactId": contactID, "text": text, "method": "auto"])
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
            if reply.setupComplete != nil { state = reply }
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

    func savePeer(host: String, port: Int) async {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test"), host == "rmap.world" {
            guard await perform("device_name", ["token": token, "name": "Family iOS simulator test"]) else { return }
        }
        #endif
        _ = await perform("peer", ["token": token, "host": host, "port": port, "enabled": true])
    }

    func saveDeviceName(_ name: String) async -> Bool {
        await perform("device_name", ["token": token, "name": name])
    }

    func addContact(name: String, address: String) async -> Bool {
        let current = state?.contacts ?? []
        let existing = current.map { contact in
            var value: [String: Any] = ["id": contact.id, "name": contact.name, "addresses": contact.addresses]
            value["identityPublicKey"] = contact.identityPublicKey
            return value
        }
        let lxmf = address.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard lxmf.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else {
            error = "Enter the contact’s 32-character LXMF address."
            return false
        }
        let contact: [String: Any] = [
            "id": (current.map(\.id).max() ?? 0) + 1,
            "name": name.trimmingCharacters(in: .whitespacesAndNewlines),
            "addresses": ["lxmf": lxmf]
        ]
        return await perform("contacts", ["token": token, "contacts": existing + [contact]])
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
                    Section("Connection") {
                        Text(state.tcpOnline == true ? "Reticulum TCP connected" : "Reticulum TCP offline")
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
                    Section("Approved contacts") {
                        ForEach(state.contacts ?? []) { contact in
                            NavigationLink(contact.name) { FamilyChat(family: family, contact: contact) }
                        }
                        Button("Guardian settings") { showGuardian = true }
                    }
                    if !family.notificationsAllowed {
                        Button("Enable message notifications") { Task { await family.enableNotifications() } }
                    }
                } else {
                    ProgressView("Starting Family")
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
            .navigationTitle(family.state?.deviceName ?? "neXt Family")
            .preferredColorScheme(appearance.isEmpty ? nil : appearance == "night" ? .dark : .light)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(night ? "Day mode" : "Night mode", systemImage: night ? "sun.max" : "moon") {
                        appearance = night ? "day" : "night"
                    }
                    .accessibilityIdentifier("appearance-toggle")
                }
            }
            .sheet(isPresented: $showGuardian, onDismiss: { Task { await family.lock() } }) {
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
    @State private var name = ""
    @State private var address = ""
    @State private var contactSaved = false
    @State private var mailboxAddress = ""
    @State private var mailboxSaved = false
    @State private var deviceName = ""
    @State private var deviceNameSaved = false
    @State private var showPassword = false

    var body: some View {
        NavigationStack {
            Form {
                if family.unlocked {
                    Section("Device name") {
                        TextField("Device name", text: $deviceName)
                            .accessibilityIdentifier("device-name")
                        Button("Save device name") {
                            Task { deviceNameSaved = await family.saveDeviceName(deviceName) }
                        }
                        if deviceNameSaved { Text("Device name saved") }
                    }
                    .onAppear {
                        deviceName = family.state?.deviceName ?? "neXt Family"
                        if let peer = family.state?.peer {
                            host = peer.host
                            port = String(peer.port)
                        }
                        #if DEBUG
                        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test") {
                            host = ProcessInfo.processInfo.environment["FAMILY_TEST_HOST"] ?? host
                            port = ProcessInfo.processInfo.environment["FAMILY_TEST_PORT"] ?? port
                        }
                        #endif
                    }
                    Section("Reticulum TCP peer") {
                        TextField("Host", text: $host).textInputAutocapitalization(.never)
                            .accessibilityIdentifier("peer-host")
                        TextField("Port", text: $port).keyboardType(.numberPad)
                            .accessibilityIdentifier("peer-port")
                        Button("Save peer") { Task { await family.savePeer(host: host, port: Int(port) ?? 0) } }
                    }
                    Section("Approve contact") {
                        TextField("Contact name", text: $name)
                            .accessibilityIdentifier("contact-name")
                        TextField("LXMF address", text: $address).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .accessibilityIdentifier("contact-address")
                        Button("Save approved contact") {
                            Task { contactSaved = await family.addContact(name: name, address: address) }
                        }
                        if contactSaved { Text("Contact saved") }
                    }
                    Section("Offline message mailbox") {
                        TextField("LXMF propagation node address", text: $mailboxAddress)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button("Save mailbox") { Task { mailboxSaved = await family.saveMailbox(mailboxAddress) } }
                        if mailboxSaved { Text("Mailbox setting saved") }
                        Text("Leave blank to disable. Senders must use this mailbox for offline delivery.")
                            .font(.caption)
                    }
                    .onAppear { mailboxAddress = family.state?.mailbox?.address ?? "" }
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
            .navigationTitle("Guardian settings")
            .onAppear {
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--isolated-family-test") {
                    host = ProcessInfo.processInfo.environment["FAMILY_TEST_HOST"] ?? host
                    port = ProcessInfo.processInfo.environment["FAMILY_TEST_PORT"] ?? port
                }
                #endif
            }
            .toolbar { Button("Done") { dismiss() } }
        }
    }
}

struct FamilyChat: View {
    @ObservedObject var family: FamilyModel
    let contact: FamilyContact
    @State private var draft = ""
    @State private var submitting = false

    var body: some View {
        Form {
            Section("Messages") {
                ForEach(family.state?.messages?[String(contact.id)] ?? []) { message in
                    VStack(alignment: .leading) {
                        Text(message.text)
                        Text(message.status).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Section {
                TextField("Message", text: $draft).accessibilityIdentifier("message-draft")
                Button("Send") {
                    let text = draft
                    submitting = true
                    Task {
                        if await family.send(contactID: contact.id, text: text),
                           draft == text { draft = "" }
                        submitting = false
                    }
                }
                .disabled(submitting || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                #if DEBUG
                if family.testNotificationDelivered { Text("Message notification delivered") }
                if family.testTCPRecovered { Text("Reticulum TCP reconnected") }
                #endif
            }
        }
        .navigationTitle(contact.name)
    }
}
