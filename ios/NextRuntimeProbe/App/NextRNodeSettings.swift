import SwiftUI

struct NextRNodeSettings: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    @State private var profile = NextRNodeProfile()
    @State private var runtime: Runtime?
    @State private var loaded = false
    @State private var saving = false
    @State private var message = ""
    @State private var failure = ""
    @FocusState private var editing: Bool

    private struct Battery: Decodable { let percent: Double; let state: String }
    private struct Runtime: Decodable {
        let online: Bool
        let connecting: Bool
        let error: String
        let battery: Battery?
    }
    private struct Snapshot: Decodable {
        let settings: NextRNodeProfile?
        let runtime: Runtime
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(!profile.enabled ? "Off" : runtime?.online == true ? "Connected" : runtime?.connecting == true ? "Connecting…" : "Not connected")
                        .accessibilityIdentifier("next-rnode-status")
                    if let battery = runtime?.battery {
                        LabeledContent("Radio battery", value: "\(Int(battery.percent))% · \(battery.state)")
                    }
                    if let problem = runtime?.error, !problem.isEmpty { Text(problem).foregroundStyle(.red) }
                    Toggle("Enable RNode", isOn: $profile.enabled).accessibilityIdentifier("next-rnode-enabled")
                    Picker("Connection", selection: Binding(get: { profile.transport }, set: {
                        profile.transport = $0; profile.endpoint = ""
                    })) {
                        Text("Bluetooth LE").tag("ble")
                        Text("Wi-Fi").tag("tcp")
                    }.pickerStyle(.segmented).accessibilityIdentifier("next-rnode-transport")
                    if profile.transport == "ble" {
                        FamilyBluetoothPicker(selection: $profile.endpoint)
                        if !profile.endpoint.isEmpty { Text(profile.endpoint).font(.caption.monospaced()).textSelection(.enabled) }
                    } else {
                        TextField("RNode hostname or IPv4 address", text: $profile.endpoint)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($editing).accessibilityIdentifier("next-rnode-endpoint")
                    }
                } header: {
                    Text("RNode connection")
                } footer: {
                    Text(profile.transport == "ble" ? "For a first connection, enable pairing mode on the radio itself and enter its PIN when iOS asks. Disconnect other apps from that radio before connecting neXt." : "Enter the radio hostname without a port. RNode uses TCP port 7633.")
                }
                Section("Radio settings") {
                    TextField("Frequency in MHz", value: $profile.frequency, format: .number)
                        .keyboardType(.decimalPad).focused($editing).accessibilityIdentifier("next-rnode-frequency")
                    TextField("Bandwidth in kHz", value: $profile.bandwidth, format: .number)
                        .keyboardType(.decimalPad).focused($editing)
                    Stepper("Spreading factor: \(profile.sf)", value: $profile.sf, in: 5...12)
                    Stepper("Coding rate: 4/\(profile.cr)", value: $profile.cr, in: 5...8)
                    Stepper("TX power: \(profile.power) dBm", value: $profile.power, in: 0...30)
                }
                Section {
                    Button("Save RNode settings") {
                        editing = false; saving = true; message = ""; failure = ""
                        Task {
                            defer { saving = false }
                            do {
                                let state = try await fetch(profile: profile)
                                runtime = state.runtime
                                message = "RNode settings saved"
                            } catch { failure = "RNode settings could not be saved. Check the address and radio settings, then try again." }
                        }
                    }.disabled(!loaded || saving || !profile.canSave).accessibilityIdentifier("next-rnode-save")
                    if !message.isEmpty { Text(message) }
                    if !failure.isEmpty { Text(failure).foregroundStyle(.red) }
                } footer: {
                    Text("Saved radios reconnect when neXt is running. Bluetooth packets can wake neXt while locked; iOS still controls background availability.")
                }
            }
            .accessibilityIdentifier("next-rnode-form")
            .navigationTitle("RNode")
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done typing") { editing = false } }
            }
            .task {
                while !Task.isCancelled {
                    do {
                        let state = try await fetch()
                        if !loaded { profile = state.settings ?? NextRNodeProfile(); loaded = true }
                        runtime = state.runtime
                    } catch { if !loaded { failure = "RNode settings are unavailable. Check that neXt is running." } }
                    do { try await Task.sleep(for: .seconds(2)) } catch { return }
                }
            }
        }
    }

    private func fetch(profile: NextRNodeProfile? = nil) async throws -> Snapshot {
        guard let url = URL(string: "/api/v1/preview/rnode", relativeTo: base) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        if let profile {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(profile)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(Snapshot.self, from: data)
    }
}
