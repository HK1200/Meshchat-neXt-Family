import Foundation
import SwiftUI

/// Matches the Android home indicators. Voltage is approximate, not a charging signal.
enum FamilyBatteryLevel {
    static func rnode(_ percent: Double) -> Int? {
        guard percent.isFinite, (0...100).contains(percent) else { return nil }
        return Int(ceil(percent / 25)) * 25
    }
    static func meshCore(_ voltage: Int) -> Int? {
        guard (2500...4500).contains(voltage) else { return nil }
        switch voltage {
        case ...3300: return 0
        case ..<3600: return 25
        case ..<3800: return 50
        case ..<4000: return 75
        default: return 100
        }
    }
}

struct FamilyMeshCoreStatus: View {
    let radio: FamilyMeshCoreState
    var body: some View {
        Text(radio.connected ? "MeshCore connected" : "MeshCore offline")
        if radio.connected, let battery = radio.battery, let level = FamilyBatteryLevel.meshCore(battery.voltage_mv) {
            Label("MeshCore battery: \(Double(battery.voltage_mv) / 1000, specifier: "%.2f") V · approximate level", systemImage: "battery.\(level)")
                .font(.caption)
        }
        if !radio.error.isEmpty { Text(radio.error).font(.caption).foregroundStyle(.secondary) }
    }
}
