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
                    } else {
                        await family.lock()
                    }
                    while !Task.isCancelled && (scenePhase == .active || family.finishingSend) {
                        await family.refresh()
                        do { try await Task.sleep(for: .seconds(1)) }
                        catch { break }
                    }
                }
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
    #endif
    weak var notifications: FamilyNotifications?
    private var sendTask: UIBackgroundTaskIdentifier = .invalid
    private var sendsStarting = 0
    private var guardianEpoch = 0
    var finishingSend: Bool { sendTask != .invalid }

    private let client = FamilyClient()
    private var token = ""

    func refresh() async {
        do {
            state = try await request("status")
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

    func addContact(name: String, address: String) async -> Bool {
        let current = state?.contacts ?? []
        let existing = current.map { ["id": $0.id, "name": $0.name, "addresses": $0.addresses] as [String: Any] }
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
            .navigationTitle("neXt Family TCP")
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

    var body: some View {
        NavigationStack {
            Form {
                if family.unlocked {
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
                } else {
                    SecureField("Guardian password", text: $password)
                        .accessibilityIdentifier("unlock-password")
                    Button("Unlock") { Task { await family.unlock(password); password = "" } }
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
                #endif
            }
        }
        .navigationTitle(contact.name)
    }
}
