import XCTest
@testable import FamilyLive

final class FamilyContactAddressMergeTests: XCTestCase {
    func testAddingMeshCoreKeepsCallingAndMessagingAddresses() {
        let old = ["lxmf": "messaging", "lxst": "voice", "sip": "sip:123@example.invalid"]
        let result = FamilyContactAddressMerge.apply(["meshcore": "radio"], to: old)
        XCTAssertEqual(result, old.merging(["meshcore": "radio"]) { _, new in new })
    }
    func testEmptyAndUnknownFieldsCannotEraseSavedServices() {
        let old = ["lxmf": "existing", "sip": "existing SIP"]
        XCTAssertEqual(FamilyContactAddressMerge.apply(["lxmf": "  ", "sip": "", "name": "Other name"], to: old), old)
    }
    func testExplicitReplacementChangesOnlyThatService() {
        XCTAssertEqual(FamilyContactAddressMerge.apply(["sip": " new SIP "], to: ["sip": "old", "meshcore": "radio"]),
                       ["sip": "new SIP", "meshcore": "radio"])
    }
}
