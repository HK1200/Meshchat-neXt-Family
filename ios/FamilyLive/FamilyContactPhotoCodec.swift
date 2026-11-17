import ImageIO
import UIKit

enum FamilyContactPhotoCodec {
    static func encode(_ data: Data) throws -> String {
        guard data.count <= 5 * 1024 * 1024,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
              width > 0, height > 0, width <= 40_000_000 / height else {
            throw PhotoError.invalid
        }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 512
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            throw PhotoError.invalid
        }
        let image = UIImage(cgImage: thumbnail)
        let side = min(image.size.width, image.size.height)
        let scale = 256 / side
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let encoded = UIGraphicsImageRenderer(size: CGSize(width: 256, height: 256), format: format).pngData { _ in
            image.draw(in: CGRect(x: (256 - image.size.width * scale) / 2,
                                  y: (256 - image.size.height * scale) / 2,
                                  width: image.size.width * scale, height: image.size.height * scale))
        }
        return "data:image/png;base64," + encoded.base64EncodedString()
    }

    enum PhotoError: LocalizedError {
        case invalid
        var errorDescription: String? { "Choose a readable photo up to 5 MB and 40 megapixels." }
    }
}
