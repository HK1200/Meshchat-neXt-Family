import XCTest
@testable import FamilyLive

final class FamilyMessageMethodTests: XCTestCase {
    private let contact = FamilyContact(id: 7, name: "Approved", addresses: ["lxmf": "lxmf", "meshcore": "radio"])
    private let reticulum = FamilyMessageRoute(service: "reticulum", reason: "Available")
    private let meshcore = FamilyMessageRoute(service: "meshcore", reason: "Available")

    private func policy(_ routes: [FamilyMessageRoute], text: String = "Hello", files: Bool = false,
                        current: FamilyContact? = nil) -> FamilyMessagePolicy {
        FamilyMessagePolicy(original: contact, current: current ?? contact,
                            routes: routes, text: text, hasAttachments: files)
    }

    func testRuntimeRoutesDecodeAndOnlyApprovedMessagingServicesAreOffered() throws {
        let reply = try JSONDecoder().decode(FamilyReply.self, from: Data(
            #"{"ok":true,"messageRoutes":{"7":[{"service":"meshcore","reason":"Recent delivery confirmations"}]}}"#.utf8))
        XCTAssertEqual(reply.messageRoutes?["7"]?.first?.service, "meshcore")
        XCTAssertEqual(policy([meshcore, FamilyMessageRoute(service: "sip", reason: "Unknown"),
                               FamilyMessageRoute(service: "auto", reason: "Unknown")]).available, [.meshcore])
    }

    func testAutomaticStillWorksWhenManualChoiceDisconnects() {
        let options = policy([reticulum])
        XCTAssertNil(options.issue(for: .automatic))
        XCTAssertNotNil(options.issue(for: .meshcore))
        XCTAssertNil(options.issue(for: .reticulum))
        XCTAssertNotNil(policy([]).issue(for: .automatic))
    }

    func testMeshCoreByteLimitCountsUnicodeAndReticulumRemainsAnOption() {
        XCTAssertNil(policy([meshcore], text: String(repeating: "é", count: 80)).issue(for: .meshcore))
        XCTAssertNotNil(policy([meshcore], text: String(repeating: "é", count: 81)).issue(for: .automatic))
        XCTAssertNotNil(policy([reticulum, meshcore], text: String(repeating: "é", count: 81)).issue(for: .meshcore))
        XCTAssertNil(policy([reticulum, meshcore], text: String(repeating: "é", count: 81)).issue(for: .automatic))
    }

    func testAttachmentsRequireReticulumEvenWhenMeshCoreRanksFirst() {
        let options = policy([meshcore, reticulum], files: true)
        XCTAssertNil(options.issue(for: .automatic))
        XCTAssertNil(options.issue(for: .reticulum))
        XCTAssertNotNil(options.issue(for: .meshcore))
        XCTAssertNotNil(policy([meshcore], files: true).issue(for: .automatic))
    }

    func testChangedApprovalStopsBothManualAndAutomaticRoutes() {
        let changed = FamilyContact(id: 7, name: "Approved", addresses: ["lxmf": "lxmf", "meshcore": "different radio"])
        for method in FamilyMessageMethod.allCases {
            XCTAssertNotNil(policy([reticulum, meshcore], current: changed).issue(for: method))
            let removed = FamilyMessagePolicy(original: contact, current: nil, routes: [reticulum], text: "Draft", hasAttachments: false)
            XCTAssertNotNil(removed.issue(for: method))
        }
        let renamed = FamilyContact(id: 7, name: "New nickname", addresses: contact.addresses)
        XCTAssertNil(policy([reticulum], current: renamed).issue(for: .automatic))
    }

    func testCharacterLimitMatchesRuntimeUnicodeScalars() {
        XCTAssertNil(policy([reticulum], text: String(repeating: "a", count: 4096)).issue(for: .automatic))
        XCTAssertNotNil(policy([reticulum], text: String(repeating: "a", count: 4097)).issue(for: .automatic))
        // A combined character is one Swift Character but two Python code points.
        XCTAssertNotNil(policy([reticulum], text: String(repeating: "e\u{301}", count: 2049)).issue(for: .automatic))
    }
}
