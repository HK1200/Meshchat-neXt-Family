import CoreImage
import XCTest
@testable import FamilyLive

final class FamilyContactQRRendererTests: XCTestCase {
    private func decoded(_ png: Data) throws -> String? {
        // Core Image emits one pixel per QR module. Decode at the same
        // integer-scaled resolution used by the nearest-neighbor UI image.
        let raw = try XCTUnwrap(CIImage(data: png))
        let image = raw.transformed(by: CGAffineTransform(scaleX: 8, y: 8))
        let detector = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode, context: CIContext(),
                                               options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]))
        let codes = detector.features(in: image).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        XCTAssertEqual(codes.count, 1)
        return codes.first
    }

    func testMessagingAddressEncodesAsTheExactScannableLXMFURI() async throws {
        let renderer = FamilyContactQRRenderer()
        let payload = "lxmf://" + String(repeating: "a1", count: 16)
        let png = await renderer.image(for: payload)
        XCTAssertEqual(try decoded(XCTUnwrap(png)), payload)
    }

    func testFamilyCardBytesSurviveRenderingWithoutChangingItsNamesOrAddresses() async throws {
        let renderer = FamilyContactQRRenderer()
        let payload = "{\"name\":\"Family test\",\"addresses\":{\"lxmf\":\"" + String(repeating: "b2", count: 16) + "\"}}"
        let png = await renderer.image(for: payload)
        XCTAssertEqual(try decoded(XCTUnwrap(png)), payload)
    }

    func testCacheChangesWithThePayloadAndRejectsUnrenderableInput() async throws {
        let renderer = FamilyContactQRRenderer()
        let first = "lxmf://" + String(repeating: "1", count: 32)
        let second = "lxmf://" + String(repeating: "2", count: 32)
        let one = await renderer.image(for: first)
        let repeated = await renderer.image(for: first)
        let two = await renderer.image(for: second)
        XCTAssertEqual(try XCTUnwrap(one), try XCTUnwrap(repeated))
        XCTAssertNotEqual(one, two)
        XCTAssertEqual(try decoded(XCTUnwrap(two)), second)
        let empty = await renderer.image(for: "")
        let oversized = await renderer.image(for: String(repeating: "x", count: 8_193))
        XCTAssertNil(empty); XCTAssertNil(oversized)
    }

    func testCancelledRenderingDoesNotReplaceTheCurrentCard() async throws {
        let renderer = FamilyContactQRRenderer()
        let current = "lxmf://" + String(repeating: "3", count: 32)
        let first = await renderer.image(for: current)
        let cancelled = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return await renderer.image(for: "cancelled")
        }
        let rejected = await cancelled.value
        XCTAssertNil(rejected)
        let remaining = await renderer.image(for: current)
        XCTAssertEqual(try XCTUnwrap(first), try XCTUnwrap(remaining))
        XCTAssertEqual(try decoded(XCTUnwrap(remaining)), current)
    }
}
