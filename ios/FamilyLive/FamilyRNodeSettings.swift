import SwiftUI

struct FamilyRNodeSettings: View {
    @ObservedObject var family: FamilyModel
    @State private var enabled = false
    @State private var endpoint = ""
    @State private var transport = "tcp"
    @State private var frequency = "914.875"
    @State private var bandwidth = "125"
    @State private var spreadingFactor = 8
    @State private var codingRate = 7
    @State private var power = 17
    @State private var saving = false
    @State private var saved = false

    var body: some View {
        Form {
            if family.unlocked {
                Section {
                    Toggle("Enable RNode", isOn: $enabled)
                    Picker("Connection", selection: $transport) {
                        Text("Wi-Fi").tag("tcp")
                        Text("Bluetooth LE").tag("ble")
                    }
                    if transport == "ble" { FamilyBluetoothPicker(selection: $endpoint) }
                    TextField(transport == "ble" ? "Bluetooth radio identifier" : "RNode hostname or IPv4 address", text: $endpoint)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("Frequency in MHz", text: $frequency).keyboardType(.decimalPad)
                    TextField("Bandwidth in kHz", text: $bandwidth).keyboardType(.decimalPad)
                    Stepper("Spreading factor: \(spreadingFactor)", value: $spreadingFactor, in: 5...12)
                    Stepper("Coding rate: 4/\(codingRate)", value: $codingRate, in: 5...8)
                    Stepper("TX power: \(power) dBm", value: $power, in: 0...30)
                    Button(saved ? "RNode settings saved" : "Save RNode settings") {
                        saving = true
                        Task {
                            saved = await family.saveRNode([
                                "enabled": enabled, "transport": transport, "endpoint": endpoint,
                                "frequency": frequency, "bandwidth": bandwidth,
                                "sf": spreadingFactor, "cr": codingRate, "power": power
                            ])
                            saving = false
                        }
                    }
                    .disabled(saving || endpoint.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if let error = family.state?.rnodeRuntime?.error, !error.isEmpty {
                        Text(error).foregroundStyle(.red)
                    }
                    if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                } footer: {
                    Text(transport == "ble" ? "Select the identifier of your Bluetooth LE RNode. Keep the radio nearby and disconnect it from other apps." : "Enter the radio’s network address. RNode listens on TCP port 7633.")
                }
            }
        }
        .navigationTitle("RNode")
        .onAppear {
            if let radio = family.state?.rnode {
                enabled = radio.enabled
                transport = radio.transport ?? "tcp"
                endpoint = radio.endpoint
                frequency = String(radio.frequency)
                bandwidth = String(radio.bandwidth)
                spreadingFactor = radio.sf
                codingRate = radio.cr
                power = radio.power
            }
        }
    }
}
