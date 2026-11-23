// SPDX-License-Identifier: 0BSD
import SwiftUI

struct FamilyCallAlertRouteEditor: View {
    @ObservedObject var family: FamilyModel
    let contactID: Int
    @Environment(\.dismiss) private var dismiss
    @State private var provider = ""
    @State private var audience = ""
    @State private var saved = false
    @State private var busy = true
    @State private var error = ""
    @FocusState private var typing: Bool

    var body: some View {
        Form {
            if family.unlocked {
                Section("This contact’s incoming call alerts") {
                    Text("Optional. Use the provider and audience supplied by this person’s call-alert setup. The saved, verified contact supplies its identity key automatically. Save any contact-address changes before editing this route.")
                        .font(.footnote).foregroundStyle(.secondary)
                    TextField("HTTPS call-alert provider", text: $provider)
                        .keyboardType(.URL).focused($typing)
                        .accessibilityIdentifier("contact-call-alert-provider")
                    TextField("Provider audience", text: $audience).focused($typing)
                        .accessibilityIdentifier("contact-call-alert-audience")
                    Button("Save call-alert route") { save(FamilyCallAlertRoute(
                        provider: provider.trimmingCharacters(in: .whitespacesAndNewlines),
                        audience: audience.trimmingCharacters(in: .whitespacesAndNewlines))) }
                        .disabled(busy || provider.isEmpty || audience.isEmpty)
                    if saved {
                        Button("Remove call-alert route", role: .destructive) { save(nil) }
                            .disabled(busy)
                    }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                Section {
                    Text("A short signed hint can wake this contact’s compatible iOS app when you call. Audio stays in Reticulum. The provider receives public routing information and the call’s identifier, timestamp and signature, without contact names, audio, messages or locations. No Apple token or enrollment password is needed here. Calls still proceed if the provider is unavailable.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } else { Text("Unlock Guardian settings to edit this route.") }
        }
        .navigationTitle("Contact call alerts")
        .toolbar { if typing { Button("Done typing") { typing = false; FamilyKeyboard.dismiss() } } }
        .task {
            defer { busy = false }
            guard family.unlocked else { return }
            do {
                if let route = try await family.loadCallAlertRoute(contactID: contactID) {
                    provider = route.provider; audience = route.audience; saved = true
                }
            } catch { self.error = error.localizedDescription }
        }
    }
    private func save(_ route: FamilyCallAlertRoute?) {
        guard family.unlocked, !busy else { return }
        typing = false; FamilyKeyboard.dismiss(); busy = true
        Task {
            defer { busy = false }
            do { try await family.saveCallAlertRoute(contactID: contactID, route: route); dismiss() }
            catch { self.error = error.localizedDescription }
        }
    }
}
