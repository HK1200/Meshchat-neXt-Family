import XCTest
@testable import FamilyLive

final class FamilyRadioBatteryTests: XCTestCase {
    func testRNodeLevelsMatchReportedPercentageWithoutGuessingChargeState() {
        for (percent, level) in [(0.0, 0), (1, 25), (25, 25), (26, 50), (76, 100), (100, 100)] {
            XCTAssertEqual(FamilyBatteryLevel.rnode(percent), level)
        }
        for invalid in [-1.0, 101, .infinity, .nan] { XCTAssertNil(FamilyBatteryLevel.rnode(invalid)) }
    }
    func testCompanionVoltageMatchesAndroidThresholdsAndUnknownReadingsStayUnknown() {
        for (voltage, level) in [(2500, 0), (3300, 0), (3301, 25), (3600, 50), (3800, 75), (4000, 100), (4500, 100)] {
            XCTAssertEqual(FamilyBatteryLevel.meshCore(voltage), level)
        }
        XCTAssertNil(FamilyBatteryLevel.meshCore(0))
        XCTAssertNil(FamilyBatteryLevel.meshCore(4501))
    }
}
