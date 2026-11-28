import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Decode at the display/quality size instead of allocating the full camera
/// bitmap. The original attachment is never replaced by its preview.
enum FamilyAttachmentPhoto {
    private static func thumbnail(_ source: CGImageSource?, pixels: Int) -> CGImage? {
        guard (1...4096).contains(pixels), let source,
              CGImageSourceGetCount(source) > 0 else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: pixels
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }
    private static func jpeg(_ image: CGImage, quality: Double) throws -> Data {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data as CFMutableData, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw CocoaError(.fileWriteUnknown)
        }
        CGImageDestinationAddImage(destination, image,
            [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
        return data as Data
    }
    static func preview(_ data: Data, pixels: Int = 90) -> Data? {
        let source = CGImageSourceCreateWithData(data as CFData,
            [kCGImageSourceShouldCache: false] as CFDictionary)
        guard let image = thumbnail(source, pixels: pixels) else { return nil }
        return try? jpeg(image, quality: 0.75)
    }
    static func preview(at file: URL, pixels: Int = 1280) -> Data? {
        let source = CGImageSourceCreateWithURL(file as CFURL,
            [kCGImageSourceShouldCache: false] as CFDictionary)
        guard let image = thumbnail(source, pixels: pixels) else { return nil }
        return try? jpeg(image, quality: 0.75)
    }
    static func prepare(_ original: Data, kind: String, quality: String, sequence: Int) throws -> FamilyDraftAttachment {
        let payload: Data
        let name: String
        let imageType: String
        if quality == "Original" {
            guard (1...FamilyDraftAttachment.limit).contains(original.count) else { throw CocoaError(.fileReadTooLarge) }
            payload = original; name = "Photo \(sequence).\(kind)"; imageType = kind
        } else {
            let preset: (Int, Double)
            switch quality {
            case "Low": preset = (320, 0.2)
            case "Medium": preset = (640, 0.6)
            default: preset = (1280, 0.75)
            }
            let source = CGImageSourceCreateWithData(original as CFData,
                [kCGImageSourceShouldCache: false] as CFDictionary)
            guard let image = thumbnail(source, pixels: preset.0) else { throw CocoaError(.fileReadCorruptFile) }
            payload = try jpeg(image, quality: preset.1)
            guard (1...FamilyDraftAttachment.limit).contains(payload.count) else { throw CocoaError(.fileReadTooLarge) }
            name = "Photo \(sequence).jpg"; imageType = "jpeg"
        }
        return FamilyDraftAttachment(name: name, data: payload, image: imageType, thumbnail: preview(payload))
    }
}

/// Metadata alone cannot bound a file which grows after the picker checks it.
/// Read at most the existing service limit plus one byte before rejecting it.
enum FamilyAttachmentInput {
    static func read(_ file: URL, limit: Int = FamilyDraftAttachment.limit) throws -> Data {
        guard limit > 0, limit < Int.max else { throw CocoaError(.fileReadTooLarge) }
        let stream = try FileHandle(forReadingFrom: file)
        defer { try? stream.close() }
        var result = Data()
        while result.count <= limit {
            let available = min(65_536, limit - result.count + 1)
            guard let chunk = try stream.read(upToCount: available), !chunk.isEmpty else { break }
            result.append(chunk)
        }
        guard !result.isEmpty else { throw CocoaError(.fileReadCorruptFile) }
        guard result.count <= limit else { throw CocoaError(.fileReadTooLarge) }
        return result
    }
}
