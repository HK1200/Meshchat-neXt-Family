import CryptoKit
import XCTest
@testable import FamilyLive

final class FamilyMapPackageTests: XCTestCase {
    func testCoverageMatchesAndroidAndRejectsInvalidCoordinates() {
        XCTAssertTrue(FamilyMapPackage.covers(latitude: 48.75, longitude: -122.48))
        XCTAssertTrue(FamilyMapPackage.covers(latitude: 42, longitude: -128))
        XCTAssertTrue(FamilyMapPackage.covers(latitude: 53, longitude: -110))
        for point in [(41.99, -122.0), (54.0, -122.0), (48.0, -109.0), (Double.nan, -122.0)] {
            XCTAssertFalse(FamilyMapPackage.covers(latitude: point.0, longitude: point.1))
        }
    }
    func testVerificationRequiresBothSizeAndDigest() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("private-map-test")
        let bytes = Data("private fixture".utf8)
        try bytes.write(to: file)
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        XCTAssertNoThrow(try FamilyMapPackage.verify(file, bytes: Int64(bytes.count), digest: digest))
        XCTAssertThrowsError(try FamilyMapPackage.verify(file, bytes: Int64(bytes.count + 1), digest: digest))
        XCTAssertThrowsError(try FamilyMapPackage.verify(file, bytes: Int64(bytes.count), digest: String(repeating: "0", count: 64)))
        XCTAssertThrowsError(try FamilyMapPackage.verify(file))
    }
}
