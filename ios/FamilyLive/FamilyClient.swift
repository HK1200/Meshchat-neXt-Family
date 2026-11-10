import Foundation

struct FamilyContact: Codable, Identifiable, Sendable {
    let id: Int
    let name: String
    let addresses: [String: String]
    var identityPublicKey: String?
}

struct FamilyMessage: Decodable, Identifiable, Sendable {
    let id: String
    let text: String
    let status: String
    let incoming: Bool
    var read: Bool?
}

struct FamilyMailbox: Decodable, Sendable {
    let address: String
    let status: String
}

struct FamilyPeer: Decodable, Sendable {
    let host: String
    let port: Int
    let enabled: Bool
}

struct FamilyReply: Decodable, Sendable {
    let ok: Bool
    var error: String?
    var token: String?
    var setupComplete: Bool?
    var tcpOnline: Bool?
    var tcpSession: String?
    var address: String?
    var deviceName: String?
    var peer: FamilyPeer?
    var mailbox: FamilyMailbox?
    var contacts: [FamilyContact]?
    var messages: [String: [FamilyMessage]]?
}

actor FamilyClient {
    private var started = false

    func request(_ json: String) throws -> FamilyReply {
        if !started {
            guard let resources = Bundle.main.resourceURL else { throw BridgeError.unavailable }
            let support = try FileManager.default.url(
                for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true
            )
            var folder = support.appendingPathComponent("FamilyTCP", isDirectory: true)
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--isolated-family-test") {
                folder = support.appendingPathComponent("SimulatorTests", isDirectory: true)
                    .appendingPathComponent(
                        UUID(uuidString: ProcessInfo.processInfo.environment["FAMILY_TEST_PROFILE"] ?? "")?.uuidString
                            ?? UUID().uuidString,
                        isDirectory: true
                    )
            }
            #endif
            let home = resources.appendingPathComponent("python").path
            let modules = resources.appendingPathComponent("staged").path
            started = family_runtime_start(home, modules, folder.path)
            guard started else { throw BridgeError.unavailable }
        }
        guard let response = family_runtime_request(json) else { throw BridgeError.unavailable }
        defer { free(response) }
        return try JSONDecoder().decode(FamilyReply.self, from: Data(String(cString: response).utf8))
    }

    private enum BridgeError: LocalizedError {
        case unavailable

        var errorDescription: String? { "The embedded Reticulum runtime could not start." }
    }
}
