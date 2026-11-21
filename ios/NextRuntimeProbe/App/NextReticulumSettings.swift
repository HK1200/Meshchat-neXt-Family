import SwiftUI
import UIKit

struct NextReticulumSettings: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    @State private var snapshot: Snapshot?
    @State private var profiles: [Profile] = []
    @State private var defaultProfile = 0
    @AppStorage("reticulumCallTarget") private var target = ""
    @State private var error = ""
    @State private var busy = false
    @FocusState private var typing: Bool

    private struct Profile: Decodable, Identifiable { let id: Int; let name: String; let available: Bool }
    private struct Profiles: Decodable { let audio_profiles: [Profile]; let default_audio_profile_id: Int }
    private struct Target: Decodable, Identifiable { let address: String; let name: String; var id: String { address } }
    private struct Call: Decodable {
        let call_id: String; let remote_identity_name: String; let status: Int
        let is_incoming: Bool; let is_mic_muted: Bool; let audio_profile_id: Int?
    }
    private struct Snapshot: Decodable {
        let enabled: Bool; let ready: Bool; let calling_available: Bool; let is_busy: Bool
        let preferred_audio_profile_id: Int?
        let address: String; let error: String; let active_call: Call?
        let call_targets: [Target]; let initiation_status: String?
    }
    var body: some View {
        NavigationStack {
            Form {
                Section("Reticulum calling") {
                    Toggle("Enable Reticulum calling", isOn: Binding(
                        get: { snapshot?.enabled ?? false },
                        set: { value in command("preview/reticulum-calling", ["enabled": value]) }))
                        .disabled(busy || snapshot?.calling_available != true)
                        .accessibilityIdentifier("next-voice-enabled")
                    Text(snapshot?.ready == true ? "Reticulum calling ready" : snapshot?.enabled == true ? (snapshot?.is_busy == true ? "Finishing the previous call…" : "Starting Reticulum calling…") : "Reticulum calling off")
                        .accessibilityIdentifier("next-voice-status")
                    if let problem = snapshot?.error, !problem.isEmpty { Text(problem).foregroundStyle(.red) }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                    if let address = snapshot?.address, !address.isEmpty {
                        Text(address).font(.caption.monospaced()).textSelection(.enabled)
                            .accessibilityIdentifier("next-voice-address")
                        ShareLink("Share voice address", item: address)
                    }
                }
                if !profiles.isEmpty {
                    Section("Voice quality") {
                        Picker("Quality", selection: Binding(
                            get: { snapshot?.active_call?.audio_profile_id ?? snapshot?.preferred_audio_profile_id ?? defaultProfile },
                            set: { value in
                                var body: [String: Any] = [:]
                                if let call = snapshot?.active_call { body["call_id"] = call.call_id }
                                command("telephone/switch-audio-profile/\(value)", body)
                            })) {
                            ForEach(profiles.filter(\.available)) { item in Text(item.name).tag(item.id) }
                        }.accessibilityIdentifier("next-voice-quality")
                        .disabled(busy || snapshot?.active_call != nil && snapshot?.active_call?.status != 6)
                    }
                }
                if let call = snapshot?.active_call {
                    Section(call.remote_identity_name) {
                        Text(call.status == 6 ? "Connected" : snapshot?.initiation_status ?? (call.is_incoming ? "Incoming call" : "Calling…"))
                            .accessibilityIdentifier("next-voice-call-state")
                        if call.is_incoming && call.status == 4 {
                            Button("Answer") { control("answer", call: call) }.accessibilityIdentifier("next-voice-answer")
                        }
                        if call.status == 6 {
                            Button(call.is_mic_muted ? "Unmute" : "Mute") {
                                control(call.is_mic_muted ? "unmute-microphone" : "mute-microphone", call: call)
                            }.accessibilityIdentifier("next-voice-mute")
                            if UIDevice.current.userInterfaceIdiom == .pad {
                                Text("Audio uses the iPad speaker or your connected headset.").font(.caption)
                            }
                        }
                        Button("End call", role: .destructive) { control("hangup", call: call) }
                            .accessibilityIdentifier("next-voice-hangup")
                    }.disabled(busy)
                } else {
                    Section("Call a contact") {
                        if let contacts = snapshot?.call_targets, !contacts.isEmpty {
                            Menu("Choose a contact") {
                                ForEach(contacts) { contact in Button(contact.name) { target = contact.address; typing = false } }
                            }.accessibilityIdentifier("next-voice-choose-contact")
                        }
                        TextField("Reticulum voice or LXMF address", text: $target)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().focused($typing)
                            .accessibilityIdentifier("next-voice-target")
                        Button("Call") {
                            typing = false
                            command("telephone/call/\(target.trimmingCharacters(in: .whitespacesAndNewlines))", [:])
                        }.buttonStyle(.borderedProminent)
                            .disabled(busy || snapshot?.ready != true || target.trimmingCharacters(in: .whitespacesAndNewlines).range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) == nil)
                            .accessibilityIdentifier("next-voice-call")
                    }
                }
            }
            .accessibilityIdentifier("next-voice-form")
            .navigationTitle("Reticulum calling")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done typing") { typing = false } }
            }
            .task {
                do {
                    let options = try await get("telephone/audio-profiles", as: Profiles.self)
                    profiles = options.audio_profiles; defaultProfile = options.default_audio_profile_id
                } catch { self.error = "Voice quality options could not be loaded." }
                while !Task.isCancelled {
                    await reload()
                    do { try await Task.sleep(for: .milliseconds(500)) } catch { return }
                }
            }
        }
    }
    private func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        guard let url = URL(string: "/api/v1/" + path, relativeTo: base) else { throw URLError(.badURL) }
        let (data, response) = try await NextHTTP.shared.data(from: url)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(type, from: data)
    }
    private func reload() async {
        do { snapshot = try await get("preview/reticulum-calling", as: Snapshot.self) }
        catch { if !Task.isCancelled { self.error = "The call status could not be refreshed." } }
    }
    private func control(_ operation: String, call: Call) {
        command("telephone/" + operation, ["call_id": call.call_id])
    }
    private func command(_ path: String, _ body: [String: Any]) {
        guard !busy else { return }; busy = true; error = ""
        Task { @MainActor in
            defer { busy = false }
            do {
                struct Token: Decodable { let csrf_token: String }
                let csrfURL = URL(string: "/api/v1/auth/csrf", relativeTo: base)!
                let (csrfData, csrfResponse) = try await NextHTTP.shared.data(from: csrfURL)
                guard (csrfResponse as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.userAuthenticationRequired) }
                let csrf = try JSONDecoder().decode(Token.self, from: csrfData)
                let endpoint = URL(string: "/api/v1/" + path, relativeTo: base)!
                var request = URLRequest(url: endpoint); request.httpMethod = "POST"
                request.setValue(csrf.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
                var origin = URLComponents(url: base, resolvingAgainstBaseURL: true)!
                origin.path = ""; origin.query = nil; origin.fragment = nil
                request.setValue(origin.string, forHTTPHeaderField: "Origin")
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
                let (data, response) = try await NextHTTP.shared.data(for: request)
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["message"] as? String
                    throw NSError(domain: "Reticulum calling", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: message ?? "The call action could not be completed."])
                }
                await reload()
            } catch { self.error = error.localizedDescription }
        }
    }
}
