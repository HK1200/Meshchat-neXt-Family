import Foundation
import SwiftUI

private struct NextLocationState: Decodable {
    struct Recipient: Decodable, Identifiable { let id: String; let name: String; let service: String; let online: Bool }
    struct Session: Decodable, Identifiable {
        let target: String; let name: String; let until: TimeInterval; let duration: String; let request_id: String
        var id: String { target }
    }
    let active: Bool; let paused: Bool; let background: Bool; let error: String; let location_status: String
    let consent_epoch: Int; let recipients: [Recipient]; let sessions: [Session]
}

struct NextLocationSettings: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    @State private var state: NextLocationState?
    @State private var selected: Set<String> = []
    @State private var duration = "15"
    @State private var background = false
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                if let state {
                    if !state.sessions.isEmpty {
                        Section("Current sharing") {
                            if state.paused { Text("Paused. Resume while neXt is open to use device location.") }
                            ForEach(state.sessions) { session in
                                VStack(alignment: .leading) {
                                    Text(session.name).font(.headline)
                                    if session.until == -1 { Text("Until you stop sharing") }
                                    else { Text("Until \(Date(timeIntervalSince1970: session.until), style: .time)") }
                                    Button("Stop sharing with \(session.name)", role: .destructive) {
                                        Task { await action(["action": "stop", "target": session.target, "request_id": session.request_id]) }
                                    }.disabled(busy)
                                }
                            }
                            Button("Stop all sharing", role: .destructive) { Task { await action(["action": "stop"]) } }.disabled(busy)
                            if state.paused {
                                Button("Resume sharing") { Task { await action(["action": "resume"]) } }.disabled(busy)
                            }
                        }
                    }
                    Section {
                        ForEach(state.recipients) { recipient in
                            Toggle(isOn: Binding(get: { selected.contains(recipient.id) }, set: {
                                if $0 { selected.insert(recipient.id) } else { selected.remove(recipient.id) }
                            })) {
                                VStack(alignment: .leading) {
                                    Text(recipient.name)
                                    Text(recipient.online ? "Reticulum" : "Reticulum · waiting for a connection").font(.caption)
                                }
                            }
                        }
                        if state.recipients.isEmpty {
                            Text("Choose Browser GPS in Settings → Telemetry & Location and add a Reticulum contact or conversation first.")
                        }
                        Picker("Duration", selection: $duration) {
                            Text("15 minutes").tag("15"); Text("1 hour").tag("60")
                            Text("Until I stop sharing").tag("ongoing")
                        }
                        Toggle("Continue with the screen locked", isOn: $background)
                        Button("Start sharing") {
                            let request: [String: Any] = ["action": "start", "targets": Array(selected).sorted(),
                                "duration": duration, "background": background,
                                "request_id": UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
                                "consent_epoch": state.consent_epoch]
                            Task { await action(request) }
                        }.disabled(busy || selected.isEmpty || selected.count > 16)
                    } header: { Text("Share device location") } footer: {
                        Text("Locked-screen sharing is optional and uses more battery. Start it while neXt is open. iOS shows a location indicator. Force-quitting neXt ends the session. Updates use private Reticulum messages, never a public room or offline mailbox.")
                    }
                    if !state.location_status.isEmpty && !state.sessions.isEmpty { Text(state.location_status).font(.caption) }
                    if !state.error.isEmpty { Text(state.error).foregroundStyle(.red) }
                } else { ProgressView("Loading location controls…") }
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Location sharing")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.disabled(busy) } }
            .task {
                await refresh(initial: true)
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(3)) } catch { return }
                    await refresh()
                }
            }
        }
    }

    @MainActor private func request(_ body: [String: Any]? = nil) async throws -> NextLocationState {
        var request = URLRequest(url: URL(string: "/api/v1/preview/location-sessions", relativeTo: base)!)
        if let body {
            struct Token: Decodable { let csrf_token: String }
            let (data, response) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/auth/csrf", relativeTo: base)!)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.userAuthenticationRequired) }
            let token = try JSONDecoder().decode(Token.self, from: data)
            request.httpMethod = "POST"; request.setValue(token.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
            request.setValue("http://127.0.0.1:\(base.port!)", forHTTPHeaderField: "Origin")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await NextHTTP.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            struct Failure: Decodable { let message: String }
            let message = (try? JSONDecoder().decode(Failure.self, from: data))?.message ?? "Location controls could not finish. Check sharing status."
            throw NSError(domain: "neXt", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return try JSONDecoder().decode(NextLocationState.self, from: data)
    }
    @MainActor private func refresh(initial: Bool = false) async {
        guard !busy else { return }
        do {
            let value = try await request(); state = value
            if initial { background = value.background }
            selected.formIntersection(Set(value.recipients.map(\.id)))
        } catch { self.error = error.localizedDescription }
    }
    @MainActor private func action(_ body: [String: Any]) async {
        guard !busy else { return }; busy = true
        defer { busy = false }
        do { state = try await request(body); error = "" }
        catch { self.error = error.localizedDescription }
    }
}
