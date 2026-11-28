import CoreGraphics
import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation

/// A small, serial rendering actor keeps Core Image initialization and image
/// evaluation out of SwiftUI's main-thread body. Only the latest PNG is cached.
actor FamilyContactQRRenderer {
    static let shared = FamilyContactQRRenderer()
    private var context: CIContext?
    private var cachedPayload: String?
    private var cachedPNG: Data?

    func image(for payload: String) -> Data? {
        guard !Task.isCancelled, !payload.isEmpty, payload.utf8.count <= 8_192 else { return nil }
        if cachedPayload == payload { return cachedPNG }
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(payload.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        // Create the context lazily here, on this actor, rather than during a
        // main-thread view/static initializer. Each request owns its filter.
        let renderer = context ?? CIContext(options: [.cacheIntermediates: false])
        context = renderer
        let png = renderer.pngRepresentation(of: output, format: .RGBA8,
                                             colorSpace: CGColorSpaceCreateDeviceRGB(), options: [:])
        guard !Task.isCancelled else { return nil }
        if let png { cachedPayload = payload; cachedPNG = png }
        return png
    }
}
