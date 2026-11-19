import SwiftUI

struct FamilyMeshCoreSettings: View {
    @ObservedObject var family: FamilyModel
    @State private var enabled = false
    @State private var receive = true
    @State private var target = ""
    @State private var saving = false
    @State private var advertStatus = ""

    private func advertise(flood: Bool) {
        saving = true
        Task {
            advertStatus = await family.advertiseMeshCore(flood: flood) ? "Advert requested. Radio errors appear above." : family.error
            saving = false
        }
    }

    var body: some View {
        Form {
            if family.unlocked {
                Section("Companion radio") {
                    Toggle("Enable MeshCore", isOn: $enabled)
                    Toggle("Receive approved private messages", isOn: $receive)
                    FamilyBluetoothPicker(selection: $target)
                    if !target.isEmpty { Text("Selected radio: \(target)").font(.caption).textSelection(.enabled) }
                    Button("Save MeshCore settings") {
                        saving = true
                        Task {
                            _ = await family.saveMeshCore(["enabled": enabled, "receive": receive, "transport": "ble", "target": target])
                            saving = false
                        }
                    }.disabled(saving || target.isEmpty)
                    if let radio = family.state?.meshcore {
                        Text(radio.connected ? "Connected to \(radio.name)" : "MeshCore disconnected")
                        if let battery = radio.battery { Text("Radio battery: \(Double(battery.voltage_mv) / 1000, specifier: "%.2f") V") }
                        if !radio.error.isEmpty { Text(radio.error).foregroundStyle(.red) }
                    }
                    if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                }
                Section("Advertise this companion") {
                    Button("Send local advert") { advertise(flood: false) }
                        .disabled(family.state?.meshcore?.connected != true || saving)
                    Button("Send flood advert") { advertise(flood: true) }
                        .disabled(family.state?.meshcore?.connected != true || saving)
                    Text("An advert broadcasts the radio’s configured name, public identity, and any location stored on the radio. Local reaches nearby nodes; flood can be repeated across the mesh.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if !advertStatus.isEmpty { Text(advertStatus) }
                }
                Section("Approve a MeshCore contact") {
                    ForEach((family.state?.announces ?? []).filter { $0.service == "meshcore" }, id: \.address) { client in
                        Button("Approve \(client.name)") {
                            Task {
                                _ = await family.saveContact(name: String(client.name.prefix(32)), address: "", voiceAddress: "", meshcoreAddress: client.address)
                            }
                        }
                    }
                    Text("Nearby clients and the radio’s saved contacts appear here after connecting. Approving a contact enables private messages.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("MeshCore")
        .onAppear {
            if let config = family.state?.meshcore?.config {
                enabled = config.enabled
                receive = config.receive
                target = config.target
            }
        }
    }
}
