import Foundation
import SwiftUI

struct NextMailboxSettings: View {
    let base: URL
    let push: NextPushRegistration
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var sendFallback = false
    @State private var state: NextMailboxState?
    @State private var busy = false
    @State private var showPushSettings = false
    @State private var showRecipientAlerts = false
    @State private var saving = false
    @State private var loaded = false
    @State private var error = ""
    @FocusState private var typing: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section("Offline mailbox") {
                    Text(statusText).font(.headline).accessibilityIdentifier("next-mailbox-status")
                    Text("An LXMF propagation node can hold encrypted messages while you are offline. Enter its propagation address, not a contact’s messaging address.")
                    TextField("Propagation node address", text: $address)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .focused($typing).accessibilityIdentifier("next-mailbox-address")
                        .disabled(!loaded || saving)
                    HStack {
                        Text("Use mailbox when a direct message fails")
                        Spacer()
                        Toggle("Use mailbox when a direct message fails", isOn: $sendFallback)
                            .labelsHidden().fixedSize()
                            .accessibilityIdentifier("next-mailbox-fallback")
                            .disabled(!loaded || saving)
                    }
                    Text("Optional. Automatic delivery can leave encrypted messages at this relay if a direct send fails. The relay sees delivery metadata. Sent means relay acceptance, not receipt by the recipient.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Button("Save mailbox") {
                        typing = false
                        Task { await update(save: true) }
                    }.disabled(!loaded || busy || NextMailboxAddress.normalize(address) == nil)
                        .accessibilityIdentifier("next-mailbox-save")
                    Button("Check mailbox now") { Task { await update(sync: true) } }
                        .disabled(!loaded || busy || state?.address.isEmpty != false)
                        .accessibilityIdentifier("next-mailbox-sync")
                    Text("Leave the address blank and save to turn mailbox checks off. This does not delete saved messages.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Receiving alerts") {
                    Button("Mailbox push alerts") { showPushSettings = true }
                        .accessibilityIdentifier("next-push-settings")
                }
                Section("Sending alerts") {
                    Button("Recipient mailbox alerts") { showRecipientAlerts = true }
                        .accessibilityIdentifier("next-recipient-alerts")
                }
                Section("Status") {
                    if let stamp = state?.last_checked_at {
                        LabeledContent("Last completed check", value: Date(timeIntervalSince1970: stamp).formatted(date: .abbreviated, time: .shortened))
                    }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                    if let failure = state?.error { Text(failure).foregroundStyle(.red) }
                    Text("Checks run every five minutes while neXt is running. iOS can suspend the app when it is closed or locked; this option does not guarantee a background alert. Your sender must use a compatible mailbox to leave an offline message.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .accessibilityIdentifier("next-mailbox-form")
            .navigationTitle("Offline mailbox")
            .toolbar {
                // Background status reads must not swallow a user's Done tap.
                // Keep an explicit Save protected until its result is known.
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.disabled(saving) }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done typing") { typing = false; FamilyKeyboard.dismiss() }
                }
            }
            .sheet(isPresented: $showRecipientAlerts) { NextRecipientAlerts(base: base).interactiveDismissDisabled() }
            .sheet(isPresented: $showPushSettings) { NextPushSettings(base: base, push: push) }
            .task {
                await update(initial: true)
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(3)) } catch { break }
                    await update()
                }
            }
        }
    }

    private var statusText: String {
        guard let state else { return "Loading mailbox…" }
        switch state.status {
        case "off": return "Off"
        case "syncing": return "Checking mailbox…"
        case "complete": return "Mailbox check completed"
        case "failed": return "Check failed · will retry"
        default: return "Waiting for a Reticulum connection or the next check"
        }
    }

    @MainActor private func update(initial: Bool = false, save: Bool = false, sync: Bool = false) async {
        guard !busy else { return }
        busy = true
        saving = save
        defer { busy = false; saving = false }
        do {
            var request = URLRequest(url: URL(string: "/api/v1/preview/mailbox" + (sync ? "/sync" : ""), relativeTo: base)!)
            request.timeoutInterval = 15
            if save || sync {
                struct Token: Decodable { let csrf_token: String }
                let (tokenData, tokenResponse) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/auth/csrf", relativeTo: base)!)
                guard (tokenResponse as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.userAuthenticationRequired) }
                let token = try JSONDecoder().decode(Token.self, from: tokenData)
                request.httpMethod = "POST"
                request.setValue(token.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
                request.setValue("http://127.0.0.1:\(base.port!)", forHTTPHeaderField: "Origin")
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                if save {
                    guard let normalized = NextMailboxAddress.normalize(address) else { throw URLError(.badURL) }
                    struct Settings: Encodable { let address: String; let send_fallback: Bool }
                    request.httpBody = try JSONEncoder().encode(Settings(address: normalized, send_fallback: !normalized.isEmpty && sendFallback))
                } else { request.httpBody = Data("{}".utf8) }
            }
            let (data, response) = try await NextHTTP.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                throw NSError(domain: "neXt", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not save or check the mailbox. Your saved address is unchanged unless Save completed."])
            }
            let result = try JSONDecoder().decode(NextMailboxState.self, from: data)
            state = result
            if initial || save || !loaded { address = result.address; sendFallback = result.send_fallback == true }
            loaded = true
            error = ""
        } catch { self.error = error.localizedDescription }
    }
}
