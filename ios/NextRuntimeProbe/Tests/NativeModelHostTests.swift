import XCTest

final class NativeModelHostTests: XCTestCase {
    func testOnlyExplicitDisposableSimulatorModelHostCanStartWithoutTheAppUI() {
        XCTAssertTrue(NextNativeModelHost.enabled(simulator: true, fixturePresent: true, environment: ["NEXT_NATIVE_MODEL_HOST": "1"]))
    }
    func testPhysicalAppCannotUseTheModelHostFlag() {
        XCTAssertFalse(NextNativeModelHost.enabled(simulator: false, fixturePresent: true, environment: ["NEXT_NATIVE_MODEL_HOST": "1"]))
    }
    func testFixtureFreeAppCannotUseTheModelHostFlag() {
        XCTAssertFalse(NextNativeModelHost.enabled(simulator: true, fixturePresent: false, environment: ["NEXT_NATIVE_MODEL_HOST": "1"]))
    }
    func testNormalUITestStillStartsTheFullApp() {
        for value in [[:], ["NEXT_NATIVE_MODEL_HOST": "0"], ["NEXT_NATIVE_MODEL_HOST": "true"]] {
            XCTAssertFalse(NextNativeModelHost.enabled(simulator: true, fixturePresent: true, environment: value))
        }
    }
}
