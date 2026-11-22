import Foundation
import SwiftUI

/// Explicit public routing metadata only. Enrollment codes and APNs tokens
/// belong to the receiving app and must never enter this sender-side form.
struct NextRecipientAlerts: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    private struct Contact: Decodable, Identifiable {
        let id: Int
        let name: String
        let lxmf_address: String
    }
    private struct Contacts: Decodable { let contacts: [Contact] }
    private struct Route: Codable, Equatable { let provider: String; let audience: String; let relay: String }
    private struct Saved: Decodable { let route: Route? }
    @State private var contacts: [Contact] = []
    @State private var drafts: [Int: Route] = [:]
    @State private var selected = 0
    @State private var provider = ""
    @State private var audience = ""
    @State private var relay = ""
    @State private var saved: Route?
    @State private var busy = false
    @State private var loaded = false
    @State private var error = ""
    @State private var status = ""
    @FocusState private var typing: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section("Recipient alerts") {
                    Text("Optional. Configure this only when a contact gives you their private mailbox alert route.")
                    if contacts.isEmpty {
                        Text("Save a Reticulum messaging contact first.")
                    } else {
                        Picker("Contact", selection: $selected) {
                            ForEach(contacts) { contact in Text(contact.name).tag(contact.id) }
                        }.disabled(busy).accessibilityIdentifier("next-recipient-alert-contact")
                        Text(saved == nil ? "Off" : "Recipient alerts saved")
                            .accessibilityIdentifier("next-recipient-alert-status")
                        TextField("HTTPS alert provider", text: $provider)
                            .keyboardType(.URL).focused($typing).accessibilityIdentifier("next-recipient-alert-provider")
                        TextField("Provider name (audience)", text: $audience)
                            .focused($typing).accessibilityIdentifier("next-recipient-alert-audience")
                        TextField("Mailbox propagation address", text: $relay)
                            .focused($typing).accessibilityIdentifier("next-recipient-alert-relay")
                        Button("Save recipient alerts") { change(remove: false) }
                            .disabled(busy || !loaded || provider.isEmpty || audience.isEmpty || relay.isEmpty)
                            .accessibilityIdentifier("next-recipient-alert-save")
                        Button("Remove recipient alerts", role: .destructive) { change(remove: true) }
                            .disabled(busy || !loaded || saved == nil)
                            .accessibilityIdentifier("next-recipient-alert-remove")
                    }
                    Text("Use the same relay as the recipient’s mailbox. A signed hint is sent only after that relay accepts an encrypted message. The provider receives public routing metadata and an encrypted packet identifier, never message text or attachments.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if !status.isEmpty { Text(status).accessibilityIdentifier("next-recipient-alert-result") }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            }
            .accessibilityIdentifier("next-recipient-alert-form")
            .navigationTitle("Recipient alerts")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.disabled(busy) }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer(); Button("Done typing") { typing = false; FamilyKeyboard.dismiss() }
                }
            }
            .task {
                busy = true
                defer { busy = false }
                do {
                    contacts = try await fetch("telephone/contacts", as: Contacts.self).contacts
                    if let first = contacts.first { selected = first.id; await load(first.id) }
                } catch { self.error = "Saved contacts could not be loaded. Try reopening Recipient alerts." }
            }
            .onChange(of: selected) { old, value in
                guard old != 0, value != old else { return }
                if loaded { drafts[old] = Route(provider: provider, audience: audience, relay: relay) }
                loaded = false; saved = nil; provider = ""; audience = ""; relay = ""; status = ""; error = ""
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
            let result = try await fetch("telephone/contacts/\(contact)/mailbox-alert-route", as: Saved.self)
            guard contact == selected else { return }
            saved = result.route
            let draft = drafts[contact] ?? result.route
            provider = draft?.provider ?? ""; audience = draft?.audience ?? ""; relay = draft?.relay ?? ""; loaded = true
        } catch { if contact == selected { self.error = "Recipient alert settings could not be loaded." } }
    }

    private func change(remove: Bool) {
        typing = false; FamilyKeyboard.dismiss(); busy = true; error = ""; status = ""
        let contact = selected
        let draft = Route(provider: provider.trimmingCharacters(in: .whitespacesAndNewlines),
                          audience: audience.trimmingCharacters(in: .whitespacesAndNewlines),
                          relay: relay.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
        Task { @MainActor in
            defer { busy = false }
            do {
                struct Token: Decodable { let csrf_token: String }
                let token = try await fetch("auth/csrf", as: Token.self)
                var request = URLRequest(url: URL(string: "/api/v1/telephone/contacts/\(contact)/mailbox-alert-route", relativeTo: base)!)
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
                    throw NSError(domain: "Recipient alerts", code: 1, userInfo: [NSLocalizedDescriptionKey: problem ?? "Recipient alerts could not be saved."])
                }
                let result = try JSONDecoder().decode(Saved.self, from: data)
                guard contact == selected else { return }
                drafts.removeValue(forKey: contact)
                saved = result.route
                provider = result.route?.provider ?? ""; audience = result.route?.audience ?? ""
                relay = result.route?.relay ?? ""; loaded = true
                status = remove ? "Recipient alerts removed." : "Recipient alerts saved."
            } catch { self.error = error.localizedDescription }
        }
    }
}
