import Foundation
import SwiftUI

/// Explicit public routing metadata only. Enrollment codes and APNs tokens
/// belong to the receiving app and must never enter this sender-side form.
struct NextRecipientCallAlerts: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    private struct Contact: Decodable, Identifiable {
        let id: Int
        let name: String
        let lxmf_address: String
    }
    private struct Contacts: Decodable { let contacts: [Contact] }
    private struct Route: Codable, Equatable { let provider: String; let audience: String; let public_key: String }
    private struct Saved: Decodable { let route: Route? }
    @State private var contacts: [Contact] = []
    @State private var drafts: [Int: Route] = [:]
    @State private var selected = 0
    @State private var provider = ""
    @State private var audience = ""
    @State private var public_key = ""
    @State private var saved: Route?
    @State private var busy = false
    @State private var writing = false
    @State private var loaded = false
    @State private var error = ""
    @State private var status = ""
    private enum Field: Hashable { case provider, audience, public_key }
    @FocusState private var focused: Field?

    var body: some View {
        NavigationStack {
            Form {
                Section("Recipient call alerts") {
                    Text("Optional. Configure this only when a contact enables incoming call alerts and gives you their provider address and audience.")
                    if contacts.isEmpty {
                        Text("Save a Reticulum messaging contact first.")
                    } else {
                        Picker("Contact", selection: $selected) {
                            ForEach(contacts) { contact in Text(contact.name).tag(contact.id) }
                        }.disabled(busy).accessibilityIdentifier("next-recipient-call-alert-contact")
                        Text(!loaded ? "Loading recipient call alerts…" : saved == nil ? "Off" : "Recipient call alerts saved")
                            .accessibilityIdentifier("next-recipient-call-alert-status")
                        TextField("HTTPS alert provider", text: $provider)
                            .keyboardType(.URL).disabled(busy || !loaded).focused($focused, equals: .provider).accessibilityIdentifier("next-recipient-call-alert-provider")
                        TextField("Provider audience", text: $audience)
                            .disabled(busy || !loaded).focused($focused, equals: .audience).accessibilityIdentifier("next-recipient-call-alert-audience")
                        Text(public_key.isEmpty ? "Waiting for this contact's verified identity" : "Contact identity verified")
                            .font(.footnote).foregroundStyle(.secondary)
                            .accessibilityIdentifier("next-recipient-call-alert-key-status")
                        Button("Refresh contact identity") { Task { busy = true; defer { busy = false }; await load(selected) } }
                            .disabled(busy)
                        Button("Save recipient call alerts") { change(remove: false) }
                            .disabled(busy || !loaded || provider.isEmpty || audience.isEmpty || public_key.isEmpty)
                            .accessibilityIdentifier("next-recipient-call-alert-save")
                        Button("Remove recipient call alerts", role: .destructive) { change(remove: true) }
                            .disabled(busy || !loaded || saved == nil)
                            .accessibilityIdentifier("next-recipient-call-alert-remove")
                    }
                    Text("Saving these details sends nothing. When you call this contact, neXt asks their provider to wake their app. Ending the call also cancels the alert. The provider receives signed call details, never audio or message text. The recipient needs a push-enabled app and a compatible provider.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if !status.isEmpty { Text(status).accessibilityIdentifier("next-recipient-call-alert-result") }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            }
            .accessibilityIdentifier("next-recipient-call-alert-form")
            .navigationTitle("Recipient call alerts")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.disabled(writing) }
                ToolbarItem(placement: .topBarLeading) {
                    if focused != nil {
                        Button("Done typing") { focused = nil; FamilyKeyboard.dismiss() }
                            .accessibilityIdentifier("next-recipient-call-alert-done-typing")
                    }
                }
            }
            .task {
                busy = true
                defer { busy = false }
                do {
                    contacts = try await fetch("telephone/contacts", as: Contacts.self).contacts
                    if let first = contacts.first { selected = first.id; await load(first.id) }
                } catch { self.error = "Saved contacts could not be loaded. Try reopening Recipient call alerts." }
            }
            .onChange(of: selected) { old, value in
                guard old != 0, value != old else { return }
                if loaded { drafts[old] = Route(provider: provider, audience: audience, public_key: public_key) }
                loaded = false; saved = nil; provider = ""; audience = ""; public_key = ""; status = ""; error = ""
                Task { busy = true; defer { busy = false }; await load(value) }
            }
        }
    }

    private func fetch<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let (data, response) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/" + path, relativeTo: base)!)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(type, from: data)
    }

    @MainActor private func load(_ contact: Int) async {
        do {
            let result = try await fetch("telephone/contacts/\(contact)/call-alert-route", as: Saved.self)
            guard contact == selected else { return }
            saved = result.route
            let draft = drafts[contact] ?? result.route
            provider = draft?.provider ?? ""; audience = draft?.audience ?? ""; public_key = draft?.public_key ?? ""
            if let fresh = try? await fetch("preview/push-enrollment-state", as: NextPushState.self),
               let address = contacts.first(where: { $0.id == contact })?.lxmf_address,
               let key = fresh.contacts?.first(where: { $0.addresses["lxmf"] == address })?.identityPublicKey {
                guard contact == selected else { return }
                public_key = key
            }
            loaded = true
        } catch { if contact == selected { self.error = "Recipient call alert settings could not be loaded." } }
    }

    private func change(remove: Bool) {
        focused = nil; FamilyKeyboard.dismiss(); busy = true; writing = true; error = ""; status = ""
        let contact = selected
        let draft = Route(provider: provider.trimmingCharacters(in: .whitespacesAndNewlines),
                          audience: audience.trimmingCharacters(in: .whitespacesAndNewlines),
                          public_key: public_key.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
        Task { @MainActor in
            defer { busy = false; writing = false }
            do {
                struct Token: Decodable { let csrf_token: String }
                let token = try await fetch("auth/csrf", as: Token.self)
                var request = URLRequest(url: URL(string: "/api/v1/telephone/contacts/\(contact)/call-alert-route", relativeTo: base)!)
                request.httpMethod = remove ? "DELETE" : "POST"; request.timeoutInterval = 15
                request.setValue(token.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
                var origin = URLComponents(url: base, resolvingAgainstBaseURL: true)!
                origin.path = ""; origin.query = nil; origin.fragment = nil
                request.setValue(origin.string, forHTTPHeaderField: "Origin")
                if !remove {
                    struct Payload: Encodable { let route: Route }
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.httpBody = try JSONEncoder().encode(Payload(route: draft))
                }
                let (data, response) = try await NextHTTP.shared.data(for: request)
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    let problem = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["message"] as? String
                    throw NSError(domain: "Recipient call alerts", code: 1, userInfo: [NSLocalizedDescriptionKey: problem ?? "Recipient call alerts could not be saved."])
                }
                let result = try JSONDecoder().decode(Saved.self, from: data)
                guard contact == selected else { return }
                drafts.removeValue(forKey: contact)
                saved = result.route
                provider = result.route?.provider ?? ""; audience = result.route?.audience ?? ""
                public_key = result.route?.public_key ?? draft.public_key; loaded = true
                status = remove ? "Recipient call alerts removed." : "Recipient call alerts saved."
            } catch { self.error = error.localizedDescription }
        }
    }
}
