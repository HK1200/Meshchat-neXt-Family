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

struct FamilyDiscoveredClient: Decodable, Identifiable, Sendable {
    let name: String
    let service: String
    let address: String
    var id: String { address }
}

struct FamilyClientLookup: Decodable, Sendable {
    let pending: Bool?
    let message: String?
    let client: FamilyDiscoveredClient?
}

struct FamilyContactCard: Decodable, Sendable {
    let name: String?
    let addresses: [String: String]
    let identityPublicKey: String?
}

struct FamilyLocationFix: Decodable, Sendable {
    let latitude: Double
    let longitude: Double
    let last_update: Double
}

struct FamilyLocationState: Decodable, Sendable {
    let mapEnabled: Bool
    let userControls: Bool
    let active: Bool
    let duration: String?
    let contactIds: [Int]
    let locations: [String: FamilyLocationFix]
}

struct FamilyRoomCard: Decodable, Sendable {
    let name: String
    let service: String
    let channel: String
    let key: String
}

struct FamilyRoom: Decodable, Identifiable, Sendable {
    let id: Int
    let name: String
    let key: String
    let channel: String
    let readOnly: Bool
    let hasPassword: Bool?
}

struct FamilyRoomMessage: Decodable, Identifiable, Sendable {
    let seq: Int
    let nick: String?
    let text: String
    let delivery: String?
    var id: Int { seq }
}

struct FamilyRoomState: Decodable, Sendable {
    let joined: Bool
    let status: String
    let error: String?
    let messages: [FamilyRoomMessage]
}

struct FamilyRoomHub: Decodable, Identifiable, Sendable {
    let hubHash: String
    let name: String
    var id: String { hubHash }
}

struct FamilyRoomListing: Decodable, Sendable {
    struct Channel: Decodable, Identifiable, Sendable {
        let channel: String
        let hasPassword: Bool
        var id: String { channel }
    }
    let hubHash: String
    let status: String
    let rooms: [Channel]
}

struct FamilyRNode: Decodable, Sendable {
    let enabled: Bool
    let endpoint: String
    let frequency: Double
    let bandwidth: Double
    let sf: Int
    let cr: Int
    let power: Int
}

struct FamilyRNodeRuntime: Decodable, Sendable {
    struct Battery: Decodable, Sendable {
        let percent: Double
        let state: String
    }
    let online: Bool
    let connecting: Bool
    let battery: Battery?
    let error: String
}

struct FamilyVoiceState: Decodable, Sendable {
    let enabled: Bool
    let ready: Bool
    let call_state: String
    let call_id: String?
    let caller_name: String?
    let address: String?
    let error: String?
    let muted: Bool?
    let profile: String?

    var active: Bool { call_state != "idle" && call_id?.isEmpty == false }
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
    var rnode: FamilyRNode?
    var rnodeRuntime: FamilyRNodeRuntime?
    var voiceSupported: Bool?
    var voice: FamilyVoiceState?
    var mailbox: FamilyMailbox?
    var location: FamilyLocationState?
    var contacts: [FamilyContact]?
    var rooms: [FamilyRoom]?
    var roomRuntime: [String: FamilyRoomState]?
    var rrcHubs: [FamilyRoomHub]?
    var roomDiscovery: [FamilyRoomListing]?
    var roomError: String?
    var rrcIdentity: String?
    var announces: [FamilyDiscoveredClient]?
    var clientLookup: FamilyClientLookup?
    var card: FamilyContactCard?
    var roomCard: FamilyRoomCard?
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
