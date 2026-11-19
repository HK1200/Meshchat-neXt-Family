import XCTest
@testable import FamilyLive

final class FamilyLocationEligibilityTests: XCTestCase {
    func testEitherMessagingServiceCanBeSelectedByGuardian() {
        for service in ["lxmf", "meshcore"] {
            XCTAssertTrue(FamilyContact(id: 1, name: "Approved", addresses: [service: "approved-address"]).canShareLocation)
        }
    }
    func testVoiceOnlyAndEmptyContactsAreNotLocationRecipients() {
        for addresses in [["sip": "sip:123@example.invalid"], ["lxst": "voice"], ["meshcore": " "], [:]] {
            XCTAssertFalse(FamilyContact(id: 1, name: "Approved", addresses: addresses).canShareLocation)
        }
    }
}
