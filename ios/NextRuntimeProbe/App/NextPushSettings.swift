import Foundation
import SwiftUI

struct NextPushSettings: View {
    let base: URL
    @ObservedObject var push: NextPushRegistration
    @Environment(\.dismiss) private var dismiss
    @State private var state: NextPushState?
    @State private var provider = ""
    @State private var secret = ""
    @State private var selected: Set<String> = []
    @State private var visible = true
    @State private var showCode = false
    @State private var error = ""
    @State private var refreshing = false
    private enum Field: Hashable { case provider, secret }
    @FocusState private var focused: Field?

    private var pushAvailable: Bool {
        let value = Bundle.main.object(forInfoDictionaryKey: "NextPushEnvironment") as? String
        return value == "development" || value == "production"
    }
    private var verified: [NextPushContact] {
        (state?.contacts ?? []).filter { $0.identityPublicKey != nil }
    }
    var body: some View {
        NavigationStack {
            Form {
                Section("Mailbox push alerts") {
                    Text(push.status).font(.headline).accessibilityIdentifier("next-push-status")
                    Text("Optional. Your chosen provider can send a private alert through Apple when neXt is suspended. Open the alert to retrieve encrypted messages from your mailbox.")
                    if !pushAvailable {
                        Text("Push alerts are unavailable in this personal preview. Radio notifications and ordinary mailbox recovery still work.")
                            .font(.footnote).foregroundStyle(.secondary)
                            .accessibilityIdentifier("next-push-unavailable")
                    }
                    if !push.configured {
                        TextField("HTTPS alert provider", text: $provider)
                            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($focused, equals: .provider).accessibilityIdentifier("next-push-provider")
                        HStack {
                            Group {
                                if showCode { TextField("Enrollment code", text: $secret) }
                                else { SecureField("Enrollment code", text: $secret) }
                            }.textInputAutocapitalization(.never).autocorrectionDisabled()
                                .focused($focused, equals: .secret).accessibilityIdentifier("next-push-code")
                            Button { showCode.toggle() } label: {
                                Label(showCode ? "Hide enrollment code" : "Show enrollment code", systemImage: showCode ? "eye.slash" : "eye")
                                    .labelStyle(.iconOnly)
                            }.buttonStyle(.borderless)
                        }
                        PasteButton(payloadType: String.self) { values in
                            if let value = values.first { secret = value.trimmingCharacters(in: .whitespacesAndNewlines) }
                        }
                        Text("The provider supplies a 64-character enrollment code. It is stored in this app’s private Keychain and is never included in a contact QR or message.")
                            .font(.footnote).foregroundStyle(.secondary)
                        Button("Enable mailbox push alerts") { enable() }
                            .disabled(!pushAvailable || push.busy || state?.mailbox?.address.isEmpty != false || selected.isEmpty || selected.count > 256 || provider.isEmpty || secret.isEmpty)
                            .accessibilityIdentifier("next-push-enable")
                    } else {
                        Button("Turn off push alerts", role: .destructive) { focused = nil; FamilyKeyboard.dismiss(); push.disable() }
                            .disabled(push.stopping).accessibilityIdentifier("next-push-disable")
                        Button("Retry provider setup") { push.retry() }.disabled(push.busy)
                    }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
                Section("Contacts allowed to send alerts") {
                    Text("\(selected.count) selected · maximum 256")
                    Text("Only verified, saved Reticulum contacts can wake this app through the provider. Adding a contact to your phonebook does not silently grant push access.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if verified.isEmpty {
                        Text("Wait for a verified announce from a saved Reticulum contact, then refresh.")
                    }
                    ForEach(Array(verified.enumerated()), id: \.offset) { _, contact in
                        if let address = contact.addresses["lxmf"] {
                            Toggle(contact.name ?? "Reticulum contact", isOn: Binding(
                                get: { selected.contains(address) },
                                set: { value in
                                    if value && selected.count < 256 { selected.insert(address) }
                                    else if !value { selected.remove(address) }
                                }))
                                .disabled(push.busy || push.stopping)
                        }
                    }
                    if push.configured && !push.stopping {
                        Button("Save allowed contacts") { updateSelection() }.disabled(push.busy || refreshing)
                    }
                    Button("Refresh saved contacts") { Task { await load(initial: false) } }
                        .disabled(refreshing || push.busy)
                }
                Section("Privacy") {
                    Text("The provider receives your Apple device token, public messaging address and the selected contacts’ public keys. Signed hints contain routing metadata and an encrypted packet identifier, never message text or attachments. Apple receives a generic alert.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("Turning alerts off stays pending until the provider confirms removal. Local radio alerts and ordinary mailbox checks keep working independently.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .accessibilityIdentifier("next-push-form")
            .navigationTitle("Mailbox push alerts")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.disabled(push.busy) }
                ToolbarItem(placement: .topBarLeading) {
                    if focused != nil {
                        Button("Done typing") { focused = nil; FamilyKeyboard.dismiss() }
                            .accessibilityIdentifier("next-push-done-typing")
                    }
                }
            }
            .task { await load(initial: true) }
            .onAppear { visible = true }
            .onDisappear { visible = false; secret = "" }
            .interactiveDismissDisabled(push.busy)
        }
    }

    @MainActor private func load(initial: Bool) async {
        guard !refreshing else { return }
        refreshing = true; defer { refreshing = false }
        do {
            let url = URL(string: "/api/v1/preview/push-enrollment-state", relativeTo: base)!
            let (data, response) = try await NextHTTP.shared.data(from: url)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            let fresh = try JSONDecoder().decode(NextPushState.self, from: data)
            state = fresh; push.refresh(fresh); error = ""
            if initial {
                if push.configured { selected = push.allowedAddresses }
                else {
                    let keys = fresh.contacts?.filter { $0.identityPublicKey != nil }.compactMap { $0.addresses["lxmf"] } ?? []
                    selected = keys.count <= 256 ? Set(keys) : []
                }
            } else {
                selected.formIntersection(Set(fresh.contacts?.compactMap { $0.addresses["lxmf"] } ?? []))
            }
        } catch { self.error = "The mailbox and contact approvals could not be loaded. Please retry." }
    }
    private func enable() {
        focused = nil; FamilyKeyboard.dismiss()
        Task {
            await load(initial: false)
            guard error.isEmpty else { return }
            await push.enable(provider: provider, secret: secret, state: state, allowedAddresses: selected,
                              stillPermitted: { visible })
            if push.configured { secret = "" }
        }
    }
    private func updateSelection() {
        Task {
            await load(initial: false)
            guard error.isEmpty, let state else { return }
            push.updateAllowedContacts(selected, state: state, stillPermitted: { visible })
        }
    }
}
