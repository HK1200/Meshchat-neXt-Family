import Foundation

struct NextRNodeProfile: Codable, Equatable {
    var enabled = false
    var transport = "ble"
    var endpoint = ""
    var frequency = 914.875
    var bandwidth = 125.0
    var sf = 8
    var cr = 7
    var power = 17

    var canSave: Bool {
        let address = endpoint.trimmingCharacters(in: .whitespacesAndNewlines)
        let validAddress = transport == "ble" ? UUID(uuidString: address) != nil :
            transport == "tcp" && address.utf8.count <= 253 &&
            address.range(of: "^[A-Za-z0-9.-]+$", options: .regularExpression) != nil
        return validAddress && frequency.isFinite && (137...1020).contains(frequency) &&
            bandwidth.isFinite && (7.8...500).contains(bandwidth) &&
            (5...12).contains(sf) && (5...8).contains(cr) && (0...30).contains(power)
    }
}
