import SwiftUI

struct FamilyBluetoothPicker: View {
    @Binding var selection: String
    @State private var devices: [Device] = []
    @State private var scanning = false
    @State private var error = ""

    private struct Device: Decodable, Identifiable {
        let id: String
        let name: String
    }
    private struct Reply: Decodable {
        let error: String?
        let devices: [Device]?
    }

    var body: some View {
        Button(scanning ? "Searching for radios…" : "Find Bluetooth radios") {
            scanning = true
        }
        .disabled(scanning)
        ForEach(devices) { device in
            Button {
                selection = device.id
            } label: {
                HStack {
                    Text(device.name)
                    Spacer()
                    if selection == device.id { Image(systemName: "checkmark") }
                }
            }
        }
        Text(error).foregroundStyle(.red)
        .task(id: scanning) {
            guard scanning else { return }
            defer { scanning = false }
            do {
                let started = try call("scan")
                if let problem = started.error { error = problem; return }
                error = ""
                for _ in 0..<8 {
                    try await Task.sleep(for: .seconds(1))
                    let reply = try call("devices")
                    devices = (reply.devices ?? []).sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
                }
                if devices.isEmpty { error = "No radios found. Check that Bluetooth LE is enabled on your radio." }
            } catch is CancellationError {
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func call(_ operation: String) throws -> Reply {
        let text = FamilyBluetooth.shared.request("{\"operation\":\"\(operation)\"}")
        return try JSONDecoder().decode(Reply.self, from: Data(text.utf8))
    }
}
