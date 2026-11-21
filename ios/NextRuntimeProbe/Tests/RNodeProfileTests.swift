import XCTest

final class RNodeProfileTests: XCTestCase {
    func testDefaultsDoNotEnableOrSelectARadio() {
        let profile = NextRNodeProfile()
        XCTAssertFalse(profile.enabled)
        XCTAssertTrue(profile.endpoint.isEmpty)
        XCTAssertFalse(profile.canSave)
        XCTAssertEqual(profile.frequency, 914.875)
        XCTAssertEqual(profile.bandwidth, 125)
        XCTAssertEqual(profile.power, 17)
    }

    func testBluetoothUUIDAndRadioLimitsAreValidatedBeforeSaving() throws {
        var profile = NextRNodeProfile()
        profile.endpoint = "2FBD5D29-9C96-4FFD-A3E7-CFF736FA5062"
        XCTAssertTrue(profile.canSave)
        profile.frequency = .nan
        XCTAssertFalse(profile.canSave)
        profile.frequency = 914.875
        profile.power = 31
        XCTAssertFalse(profile.canSave)
        profile.power = 17
        profile.endpoint = "00:11:22:33:44:55"
        XCTAssertFalse(profile.canSave)
        profile.transport = "tcp"
        profile.endpoint = "127.0.0.1"
        XCTAssertTrue(profile.canSave)
        XCTAssertEqual(try JSONDecoder().decode(NextRNodeProfile.self, from: JSONEncoder().encode(profile)), profile)
        profile.endpoint = "https://example.invalid:7633"
        XCTAssertFalse(profile.canSave)
    }
}
