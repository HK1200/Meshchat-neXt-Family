import SwiftUI

struct NextSIPSettings: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    @State private var state: Snapshot?
    @State private var draft = NextSIPAccountDraft()
    @State private var showPassword = false
    @State private var busy = false
    @State private var error = ""
    @State private var message = ""
    @FocusState private var typing: Bool

    private struct Account: Decodable, Identifiable {
        let id: String; let label: String; let `extension`: String
        let host: String; let port: Int; let allowed_networks: [String]; let save_password: Bool
    }
    private struct Snapshot: Decodable {
        let account_management_available: Bool; let registered: Bool; let state: String
        let selected: String?; let accounts: [Account]; let error: String?
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("SIP account") {
                    Text(state?.registered == true ? "SIP registered" : state?.state.replacingOccurrences(of: "_", with: " ").capitalized ?? "Loading…")
                        .accessibilityIdentifier("next-sip-status")
                    Text("Calling is not available in this preview.").foregroundStyle(.secondary)
                    if let problem = state?.error, !problem.isEmpty { Text(problem).foregroundStyle(.red) }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                    if !message.isEmpty { Text(message) }
                }
                if state?.account_management_available == true {
                    ForEach(state?.accounts ?? []) { account in
                        Section(account.label) {
                            LabeledContent("Address", value: "\(account.extension)@\(account.host):\(account.port)")
                            Button("Edit account") { edit(account) }
                            Button("Connect account") { command(["op": "connect", "id": account.id]) }
                            Button("Remove account", role: .destructive) { command(["op": "remove", "id": account.id]) }
                        }.disabled(busy)
                    }
                    Section(draft.id.isEmpty ? "Add account" : "Edit account") {
                        TextField("Account label", text: $draft.label).focused($typing)
                        TextField("Extension", text: $draft.user).focused($typing)
                            .accessibilityIdentifier("next-sip-extension")
                        TextField("Provider hostname", text: $draft.host).focused($typing)
                        TextField("Port", text: $draft.port).keyboardType(.numberPad).focused($typing)
                        Group {
                            if showPassword { TextField("Password", text: $draft.password) }
                            else { SecureField("Password", text: $draft.password) }
                        }.focused($typing).textContentType(.password)
                        Toggle("Show password", isOn: $showPassword)
                        Toggle("Save password securely", isOn: $draft.savePassword)
                        Toggle("Wi-Fi", isOn: $draft.wifi)
                        Toggle("Mobile data", isOn: $draft.mobile)
                        Toggle("Ethernet", isOn: $draft.ethernet)
                        Button("Save account") {
                            guard let payload = draft.payload else { return }
                            command(payload, saved: true)
                        }.disabled(busy || draft.payload == nil).accessibilityIdentifier("next-sip-save")
                        if !draft.id.isEmpty { Button("Add another account") { draft = NextSIPAccountDraft() } }
                    }.textInputAutocapitalization(.never).autocorrectionDisabled()
                    Section {
                        Button("Disconnect SIP") { command(["op": "disconnect"]) }.disabled(busy)
                        Text("Passwords are stored only in this app’s Keychain when saving is enabled. Choose the connections this account may use.")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("SIP accounts")
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { draft.password = ""; dismiss() } }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer(); Button("Done typing") { typing = false; FamilyKeyboard.dismiss() }
                }
            }
            .task {
                while !Task.isCancelled {
                    if !busy {
                        do { state = try await fetch() }
                        catch { self.error = "SIP settings are unavailable. Check that neXt is running." }
                    }
                    do { try await Task.sleep(for: .seconds(2)) } catch { return }
                }
            }
        }
    }

    private func edit(_ account: Account) {
        draft = NextSIPAccountDraft(id: account.id, label: account.label, user: account.extension,
            host: account.host, port: String(account.port), password: "", savePassword: account.save_password,
            wifi: account.allowed_networks.contains("wifi"), mobile: account.allowed_networks.contains("mobile"),
            ethernet: account.allowed_networks.contains("ethernet"))
        message = "Leave the password blank to keep its saved value."
    }
    private func command(_ payload: [String: Any], saved: Bool = false) {
        guard !busy else { return }
        typing = false; FamilyKeyboard.dismiss(); busy = true; error = ""; message = ""
        let submitted = draft
        Task {
            defer { busy = false }
            do {
                state = try await fetch(payload)
                if saved {
                    if draft == submitted { draft = NextSIPAccountDraft() }
                    message = "SIP account saved"
                }
            } catch { self.error = "The SIP account action failed. Check the account and connection settings, then try again." }
        }
    }
    private func fetch(_ payload: [String: Any]? = nil) async throws -> Snapshot {
        let path = payload == nil ? "/api/v1/sip/status" : "/api/v1/sip/command"
        guard let url = URL(string: path, relativeTo: base) else { throw URLError(.badURL) }
        var request = URLRequest(url: url); request.timeoutInterval = 10
        if let payload {
            struct Token: Decodable { let csrf_token: String }
            guard let tokenURL = URL(string: "/api/v1/auth/csrf", relativeTo: base), let port = base.port else { throw URLError(.badURL) }
            let (data, response) = try await NextHTTP.shared.data(from: tokenURL)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            let token = try JSONDecoder().decode(Token.self, from: data).csrf_token
            request.httpMethod = "POST"
            request.setValue(token, forHTTPHeaderField: "X-CSRF-Token")
            request.setValue("http://127.0.0.1:\(port)", forHTTPHeaderField: "Origin")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        }
        let (data, response) = try await NextHTTP.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(Snapshot.self, from: data)
    }
}
