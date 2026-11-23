// SPDX-License-Identifier: 0BSD
import Foundation
import SwiftUI

struct NextCallWakeSettings: View {
    let base: URL
    @ObservedObject var registration: NextCallWakeRegistration
    @Environment(\.dismiss) private var dismiss
    @State private var policy: NextCallWakePolicy?
    @State private var selected: Set<String> = []
    @State private var provider = ""
    @State private var audience = ""
    @State private var secret = ""
    @State private var error = ""
    @State private var loading = false
    @State private var visible = true
    @State private var showCode = false
    @FocusState private var typing: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section("Reticulum call alerts") {
                    Text(registration.status).font(.headline)
                        .accessibilityIdentifier("next-call-alert-status")
                    Text("Optional. A compatible provider can wake neXt for a call from a contact you select, even when iPadOS has suspended the app.")
                    if !NextCallWakeOwner.eligible {
                        Text("Apple call push is unavailable in this personal preview. Calls can still arrive while neXt is running. Apple enrollment and a compatible provider are needed for suspended delivery.")
                            .font(.footnote).foregroundStyle(.secondary)
                            .accessibilityIdentifier("next-call-alert-unavailable")
                    }
                    if !registration.configured {
                        TextField("HTTPS call-alert provider", text: $provider)
                            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($typing).accessibilityIdentifier("next-call-alert-provider")
                        TextField("Provider audience", text: $audience)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().focused($typing)
                            .accessibilityIdentifier("next-call-alert-audience")
                        codeField
                        Button("Enable call alerts") { enable(resuming: false) }
                            .disabled(!canReview || provider.isEmpty || audience.isEmpty || secret.isEmpty)
                            .accessibilityIdentifier("next-call-alert-enable")
                    } else {
                        Button("Turn off call alerts", role: .destructive) {
                            doneTyping(); registration.disable()
                        }.disabled(registration.stopping)
                            .accessibilityIdentifier("next-call-alert-disable")
                        Button("Retry provider setup or removal") { registration.retry() }
                            .disabled(registration.busy)
                        if registration.stopping {
                            Text("If your provider changed its code, paste the replacement to finish removal. This cannot turn alerts back on.")
                                .font(.footnote)
                            codeField
                            Button("Retry removal with this code") {
                                doneTyping()
                                if registration.updateRemovalCode(secret) { secret = "" }
                            }.disabled(registration.busy || secret.isEmpty)
                        } else if registration.needsReview {
                            Button("Confirm selected callers and resume") { enable(resuming: true) }
                                .disabled(!canReview)
                                .accessibilityIdentifier("next-call-alert-resume")
                        }
                    }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
                if let provider = registration.recipientProvider, let audience = registration.recipientAudience {
                    Section("Provider details for saved callers") {
                        LabeledContent("HTTPS provider", value: provider).textSelection(.enabled)
                        LabeledContent("Audience", value: audience).textSelection(.enabled)
                        ShareLink(item: "Reticulum call-alert provider: \(provider)\nAudience: \(audience)") {
                            Label("Share provider details", systemImage: "square.and.arrow.up")
                        }
                        Text("Shares no enrollment code, Apple token or private identity key.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section("Contacts allowed to call while suspended") {
                    Text("Select individual saved contacts. Adding a contact later does not grant call-alert access automatically.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if policy?.contacts.isEmpty != false { Text("Enable Reticulum calling and refresh after your saved contacts announce.") }
                    ForEach(Array((policy?.contacts ?? []).enumerated()), id: \.offset) { _, contact in
                        if let voice = contact.addresses["voice"] {
                            Toggle(contact.name ?? "Reticulum contact", isOn: Binding(
                                get: { selected.contains(voice) },
                                set: { value in
                                    if value && selected.count < 256 { selected.insert(voice) }
                                    else { selected.remove(voice) }
                                }))
                                .disabled(registration.configured && !registration.needsReview || registration.busy)
                        }
                    }
                    Button("Refresh call permissions") { Task { await load(initial: false) } }
                        .disabled(loading || registration.busy)
                }
                Section("Privacy and availability") {
                    Text("The provider receives your Apple call token, public identity key and the selected callers’ public voice addresses. It receives no private identity key, contact names, audio or message text. Call alerts use a separate enrollment from mailbox message alerts.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("Turning off calling, changing call permissions or removing a contact pauses alerts until you review them. A provider outage or unavailable Apple push can delay calls; this does not replace an emergency phone service.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .accessibilityIdentifier("next-call-alert-form")
            .navigationTitle("Incoming call alerts")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarLeading) {
                    if typing { Button("Done typing") { doneTyping() } }
                }
            }
            .task { await load(initial: true) }
            .onAppear { visible = true }
            .onDisappear { visible = false; secret = "" }
        }
    }
    private var codeField: some View {
        VStack(alignment: .leading) {
            HStack {
                Group {
                    if showCode { TextField("Enrollment code", text: $secret) }
                    else { SecureField("Enrollment code", text: $secret) }
                }.textInputAutocapitalization(.never).autocorrectionDisabled().focused($typing)
                    .accessibilityIdentifier("next-call-alert-code")
                Button { showCode.toggle() } label: {
                    Label(showCode ? "Hide code" : "Show code", systemImage: showCode ? "eye.slash" : "eye").labelStyle(.iconOnly)
                }.buttonStyle(.borderless)
            }
            PasteButton(payloadType: String.self) { values in
                if let first = values.first { secret = first.trimmingCharacters(in: .whitespacesAndNewlines) }
            }
            Text("Paste the provider’s 64-character code. It stays in this app’s private Keychain.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }
    private var canReview: Bool {
        NextCallWakeOwner.eligible && FamilySystemCalls.shared.enabled && !loading && !registration.busy &&
            policy?.enabled == true && !selected.isEmpty && selected.count <= 256
    }
    private func doneTyping() { typing = false; FamilyKeyboard.dismiss() }
    @MainActor private func load(initial: Bool) async {
        guard !loading else { return }
        loading = true; defer { loading = false }
        do {
            struct Token: Decodable { let csrf_token: String }
            let (tokenData, tokenResponse) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/auth/csrf", relativeTo: base)!)
            guard (tokenResponse as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.userAuthenticationRequired) }
            let csrf = try JSONDecoder().decode(Token.self, from: tokenData)
            var request = URLRequest(url: URL(string: "/api/v1/preview/call-enrollment-state", relativeTo: base)!)
            request.httpMethod = "POST"
            request.setValue(csrf.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let keys = registration.selectedCallers.map { $0.publicKey.map { String(format: "%02x", $0) }.joined() }
            request.httpBody = try JSONSerialization.data(withJSONObject: ["publicKeys": keys])
            let (data, response) = try await NextHTTP.shared.data(for: request)
            guard visible, (response as? HTTPURLResponse)?.statusCode == 200, data.count <= 262144 else { throw URLError(.badServerResponse) }
            let fresh = try JSONDecoder().decode(NextCallWakePolicy.self, from: data)
            policy = fresh; registration.policyChanged(fresh.policyDigest)
            if initial { selected = Set(registration.selectedCallers.map(\.voiceAddress)) }
            selected.formIntersection(Set(fresh.contacts.compactMap { $0.addresses["voice"] }))
            error = ""
        } catch { self.error = "Call permissions could not be loaded. Please retry." }
    }
    private func enable(resuming: Bool) {
        doneTyping()
        Task { @MainActor in
            await load(initial: false)
            guard visible, error.isEmpty, let policy, canReview else { return }
            do {
                let callers = try policy.callers(selected: selected)
                let support = try NextCallWakeOwner.support()
                let identity = try policy.ownIdentity(support: support)
                let installation = try NextCallWakeInstallation.createForOptIn(support: support)
                let accepted: Bool
                if resuming {
                    accepted = registration.resume(identity: identity, callers: callers,
                        policyDigest: policy.policyDigest, installation: installation)
                } else {
                    guard let url = URL(string: provider.trimmingCharacters(in: .whitespacesAndNewlines)) else { throw URLError(.badURL) }
                    let candidate = NextCallWakeEnrollment(provider: url,
                        audience: audience.trimmingCharacters(in: .whitespacesAndNewlines),
                        enrollmentCode: secret.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
                        installation: installation, recipientPublicKey: identity.publicKey,
                        agreementPrivateKey: identity.agreementPrivateKey, selectedCallers: callers,
                        policyDigest: policy.policyDigest)
                    accepted = registration.enable(candidate)
                }
                if accepted { secret = "" }
            } catch { self.error = "Review the provider details, selected callers and local Reticulum identity." }
        }
    }
}
