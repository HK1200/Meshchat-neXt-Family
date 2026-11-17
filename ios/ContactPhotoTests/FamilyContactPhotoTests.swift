import XCTest
@testable import FamilyLive
import ImageIO
import UIKit
import UniformTypeIdentifiers

final class FamilyContactPhotoTests: XCTestCase {
    func testCropPrivacyAndLimits() throws {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let fixture = UIGraphicsImageRenderer(size: CGSize(width: 400, height: 200), format: format).image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 100, height: 200))
            UIColor.green.setFill()
            context.fill(CGRect(x: 100, y: 0, width: 200, height: 200))
            UIColor.blue.setFill()
            context.fill(CGRect(x: 300, y: 0, width: 100, height: 200))
        }
        let tagged = NSMutableData()
        let destination = CGImageDestinationCreateWithData(tagged as CFMutableData, UTType.jpeg.identifier as CFString, 1, nil)!
        let gps: [CFString: Any] = [kCGImagePropertyGPSLatitude: 0.0, kCGImagePropertyGPSLongitude: 0.0,
                                  kCGImagePropertyGPSLatitudeRef: "N", kCGImagePropertyGPSLongitudeRef: "E"]
        CGImageDestinationAddImage(destination, fixture.cgImage!, [kCGImagePropertyGPSDictionary: gps] as CFDictionary)
        assert(CGImageDestinationFinalize(destination))
        let original = CGImageSourceCreateWithData(tagged as CFData, nil)!
        let originalProperties = CGImageSourceCopyPropertiesAtIndex(original, 0, nil)! as NSDictionary
        assert(originalProperties[kCGImagePropertyGPSDictionary] != nil)
        
        let encoded = try FamilyContactPhotoCodec.encode(tagged as Data)
        assert(encoded.hasPrefix("data:image/png;base64,"))
        let payload = Data(base64Encoded: String(encoded.split(separator: ",", maxSplits: 1)[1]))!
        let result = CGImageSourceCreateWithData(payload as CFData, nil)!
        let properties = CGImageSourceCopyPropertiesAtIndex(result, 0, nil)! as NSDictionary
        assert((properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue == 256)
        assert((properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue == 256)
        assert(properties[kCGImagePropertyGPSDictionary] == nil)
        let image = CGImageSourceCreateImageAtIndex(result, 0, nil)!
        for x in [1, 128, 254] {
            let pixel = image.cropping(to: CGRect(x: CGFloat(x), y: 128, width: 1, height: 1))!
            var bytes = [UInt8](repeating: 0, count: 4)
            bytes.withUnsafeMutableBytes { memory in
                let context = CGContext(data: memory.baseAddress, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
                                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.draw(pixel, in: CGRect(x: 0, y: 0, width: 1, height: 1))
            }
            assert(bytes[1] > 180 && bytes[0] < 70 && bytes[2] < 70, "Profile photo was not center cropped")
        }
        for invalid in [Data("not an image".utf8), Data(count: 5 * 1024 * 1024 + 1)] {
            do {
                _ = try FamilyContactPhotoCodec.encode(invalid)
                fatalError("Invalid or oversized photo accepted")
            } catch {}
        }
        print("Contact photos center-cropped to 256 pixels, GPS removed, invalid and oversized inputs rejected")
    }
}
