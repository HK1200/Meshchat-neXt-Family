import XCTest

final class SIPNetworkTests: XCTestCase {
    func testOnlyTheCurrentRouteIsReportedAndUnknownRoutesStayUnavailable() throws {
        let network = NextSIPNetwork(start: false)
        XCTAssertTrue(network.snapshot().isEmpty)
        network.update(.wifi)
        let first = try XCTUnwrap(network.snapshot().first)
        XCTAssertEqual(network.snapshot().count, 1)
        XCTAssertEqual(first["kind"], "wifi")
        XCTAssertEqual(first["address"], "system-default")
        let context = try XCTUnwrap(first["interface"])
        XCTAssertTrue(network.matches(context))
        network.update(.mobile)
        XCTAssertEqual(network.snapshot().first?["kind"], "mobile")
        XCTAssertFalse(network.matches(context))
        network.update(nil)
        XCTAssertTrue(network.snapshot().isEmpty)
    }

    func testSameKindNetworkChangeInvalidatesTheOldContext() throws {
        let network = NextSIPNetwork(start: false)
        network.update(.ethernet)
        let context = try XCTUnwrap(network.snapshot().first?["interface"])
        network.update(.ethernet)
        XCTAssertFalse(network.matches(context))
        XCTAssertEqual(network.snapshot().count, 1)
    }
}
