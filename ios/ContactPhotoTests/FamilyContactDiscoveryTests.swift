import XCTest
@testable import FamilyLive

final class FamilyContactDiscoveryTests: XCTestCase {
    func testMeshCoreSearchMatchesNameAndKeyWithoutIncludingLXMF() {
        let radio = FamilyDiscoveredClient(name: "Nearby family", service: "meshcore", address: String(repeating: "ab", count: 32))
        XCTAssertTrue(FamilyContactDiscoveryPolicy.matches(radio, service: "meshcore", query: " FAMILY ", approvedAddresses: []))
        XCTAssertTrue(FamilyContactDiscoveryPolicy.matches(radio, service: "meshcore", query: "ABAB", approvedAddresses: []))
        XCTAssertFalse(FamilyContactDiscoveryPolicy.matches(radio, service: "lxmf", query: "", approvedAddresses: []))
    }

    func testOtherApprovedContactsAreExcluded() {
        let key = String(repeating: "ab", count: 32)
        let radio = FamilyDiscoveredClient(name: "Already approved", service: "meshcore", address: key.uppercased())
        XCTAssertFalse(FamilyContactDiscoveryPolicy.matches(radio, service: "meshcore", query: "", approvedAddresses: [key]))
    }

    func testUnknownServiceAndNonmatchingSearchAreExcluded() {
        let radio = FamilyDiscoveredClient(name: "Nearby", service: "meshcore", address: String(repeating: "ab", count: 32))
        XCTAssertFalse(FamilyContactDiscoveryPolicy.matches(radio, service: "room", query: "", approvedAddresses: []))
        XCTAssertFalse(FamilyContactDiscoveryPolicy.matches(radio, service: "meshcore", query: "Someone else", approvedAddresses: []))
    }
}
