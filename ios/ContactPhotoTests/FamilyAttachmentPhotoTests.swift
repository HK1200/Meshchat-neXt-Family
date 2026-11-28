import XCTest
@testable import FamilyLive
import ImageIO
import UIKit
import UniformTypeIdentifiers

final class FamilyAttachmentPhotoTests: XCTestCase {
    private func image(width: Int = 2400, height: Int = 1200) -> Data {
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        return UIGraphicsImageRenderer(size: CGSize(width: CGFloat(width), height: CGFloat(height)), format: format).pngData { context in
            UIColor.green.setFill(); context.fill(CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
        }
    }
    private func dimensions(_ data: Data) throws -> (Int, Int) {
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        return (try XCTUnwrap(properties[kCGImagePropertyPixelWidth] as? Int),
                try XCTUnwrap(properties[kCGImagePropertyPixelHeight] as? Int))
    }
    func testOriginalPayloadIsByteExactAndItsCachedPreviewIsSmall() throws {
        let original = image()
        let prepared = try FamilyAttachmentPhoto.prepare(original, kind: "png", quality: "Original", sequence: 3)
        XCTAssertEqual(prepared.data, original); XCTAssertEqual(prepared.name, "Photo 3.png")
        XCTAssertEqual(prepared.image, "png")
        let preview = try XCTUnwrap(prepared.thumbnail), size = try dimensions(preview)
        XCTAssertLessThanOrEqual(max(size.0, size.1), 90)
        XCTAssertLessThan(preview.count, original.count)
    }
    func testExistingQualityPresetsKeepTheirDimensionsAndJPEGFormat() throws {
        let original = image()
        for (quality, pixels) in [("Low", 320), ("Medium", 640), ("High", 1280)] {
            let prepared = try FamilyAttachmentPhoto.prepare(original, kind: "png", quality: quality, sequence: 1)
            let size = try dimensions(prepared.data)
            XCTAssertEqual(size.0, pixels); XCTAssertEqual(size.1, pixels / 2)
            XCTAssertEqual(prepared.image, "jpeg"); XCTAssertEqual(prepared.name, "Photo 1.jpg")
            XCTAssertNotNil(prepared.thumbnail)
            XCTAssertEqual(prepared.data.prefix(2), Data([0xff, 0xd8]))
        }
    }
    func testSmallImagesAreNotUpscaledAndUnreadablePreviewsAreOptional() throws {
        let original = image(width: 40, height: 20)
        let preview = try XCTUnwrap(FamilyAttachmentPhoto.preview(original)), size = try dimensions(preview)
        XCTAssertEqual(size.0, 40); XCTAssertEqual(size.1, 20)
        XCTAssertNil(FamilyAttachmentPhoto.preview(Data("invalid".utf8)))
        XCTAssertNil(FamilyAttachmentPhoto.preview(original, pixels: Int.max))
        XCTAssertThrowsError(try FamilyAttachmentPhoto.prepare(Data("invalid".utf8), kind: "png", quality: "High", sequence: 1))
    }
    func testFilePreviewHasDisplayBoundsWithoutChangingTheSavedOriginal() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("photo.png"), original = image()
        try original.write(to: file)
        let preview = try XCTUnwrap(FamilyAttachmentPhoto.preview(at: file)), size = try dimensions(preview)
        XCTAssertEqual(size.0, 1280); XCTAssertEqual(size.1, 640)
        XCTAssertEqual(try Data(contentsOf: file), original)
    }
    func testResamplingAppliesOrientationAndOmitsGPSMetadata() throws {
        let source = try XCTUnwrap(CGImageSourceCreateWithData(image(width: 200, height: 100) as CFData, nil))
        let bitmap = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        let data = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(data as CFMutableData,
            UTType.jpeg.identifier as CFString, 1, nil))
        let gps: [CFString: Any] = [kCGImagePropertyGPSLatitude: 0.0, kCGImagePropertyGPSLatitudeRef: "N",
                                  kCGImagePropertyGPSLongitude: 0.0, kCGImagePropertyGPSLongitudeRef: "E"]
        CGImageDestinationAddImage(destination, bitmap,
            [kCGImagePropertyOrientation: 6, kCGImagePropertyGPSDictionary: gps] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let original = data as Data
        let prepared = try FamilyAttachmentPhoto.prepare(original, kind: "jpeg", quality: "High", sequence: 1)
        let size = try dimensions(prepared.data)
        XCTAssertEqual(size.0, 100); XCTAssertEqual(size.1, 200)
        let encoded = try XCTUnwrap(CGImageSourceCreateWithData(prepared.data as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(encoded, 0, nil) as? [CFString: Any])
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        XCTAssertEqual(try FamilyAttachmentPhoto.prepare(original, kind: "jpeg", quality: "Original", sequence: 1).data, original)
    }
    @MainActor
    func testPreparationRunsOffTheUIThreadAndKeepsTheOriginalBytes() async throws {
        let original = image()
        let result = try await Task.detached(priority: .utility) {
            let onMainThread = Thread.isMainThread
            let prepared = try FamilyAttachmentPhoto.prepare(original, kind: "png", quality: "Original", sequence: 1)
            return (prepared, onMainThread)
        }.value
        XCTAssertFalse(result.1)
        XCTAssertEqual(result.0.data, original)
        XCTAssertNotNil(result.0.thumbnail)
    }

    func testBoundedReaderAcceptsTheExactLimitAndRejectsAnExtraByte() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("file.bin")
        let original = Data(repeating: 0x7f, count: FamilyDraftAttachment.limit)
        try original.write(to: file)
        XCTAssertEqual(try FamilyAttachmentInput.read(file), original)
        let writer = try FileHandle(forWritingTo: file); try writer.seekToEnd(); try writer.write(contentsOf: Data([1])); try writer.close()
        XCTAssertThrowsError(try FamilyAttachmentInput.read(file)) { error in
            XCTAssertEqual((error as NSError).code, CocoaError.Code.fileReadTooLarge.rawValue)
        }
    }
    func testEmptyAndInvalidFileReadsFailWithoutReturningAPartialAttachment() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        try Data().write(to: file)
        XCTAssertThrowsError(try FamilyAttachmentInput.read(file))
        XCTAssertThrowsError(try FamilyAttachmentInput.read(file, limit: 0))
        XCTAssertThrowsError(try FamilyAttachmentInput.read(file, limit: Int.max))
        try Data([1, 2, 3]).write(to: file)
        for _ in 0..<100 { XCTAssertEqual(try FamilyAttachmentInput.read(file, limit: 3), Data([1, 2, 3])) }
    }
}
