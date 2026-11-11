import SwiftUI

struct FamilyRNodeSettings: View {
    @ObservedObject var family: FamilyModel
    @State private var enabled = false
    @State private var endpoint = ""
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
                    Toggle("Enable Wi-Fi RNode", isOn: $enabled)
                    TextField("RNode hostname or IPv4 address", text: $endpoint)
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
                                "enabled": enabled, "transport": "tcp", "endpoint": endpoint,
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
                    Text("Enter the radio’s network address. RNode listens on TCP port 7633.")
                }
            }
        }
        .navigationTitle("Wi-Fi RNode")
        .onAppear {
            if let radio = family.state?.rnode {
                enabled = radio.enabled
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
