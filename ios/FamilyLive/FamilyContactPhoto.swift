import ImageIO
import PhotosUI
import SwiftUI
import UIKit

struct FamilyContactAvatar: View {
    let name: String
    let photo: String?
    var size: CGFloat = 40
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Text(String(name.prefix(1)).uppercased())
                    .font(.system(size: size * 0.42, weight: .semibold))
            }
        }
        .frame(width: size, height: size)
        .background(Color.accentColor.opacity(0.15))
        .clipShape(Circle())
        .accessibilityHidden(true)
        .task(id: photo) {
            guard let photo, photo.utf8.count <= 512_000, photo.hasPrefix("data:image/"),
                  let separator = photo.firstIndex(of: ","),
                  let data = Data(base64Encoded: String(photo[photo.index(after: separator)...])) else {
                image = nil
                return
            }
            image = UIImage(data: data)
        }
    }
}

struct FamilyContactPhotoEditor: View {
    let name: String
    @Binding var photo: String?
    @Binding var loading: Bool
    @State private var selection: PhotosPickerItem?
    @State private var error = ""

    var body: some View {
        Section("Profile picture") {
            HStack(spacing: 16) {
                FamilyContactAvatar(name: name, photo: photo, size: 64)
                PhotosPicker(selection: $selection, matching: .images) {
                    Text("Choose profile picture")
                }.disabled(loading)
            }
            if photo != nil {
                Button("Remove profile picture", role: .destructive) {
                    selection = nil
                    photo = nil
                    error = ""
                }
            }
            if loading { ProgressView("Preparing picture") }
            if !error.isEmpty { Text(error).foregroundStyle(.red) }
            Text("Choose a photo up to 5 MB. A square copy stays privately on this device.")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .task(id: selection) {
            guard let selection else { return }
            loading = true
            error = ""
            defer { loading = false }
            do {
                guard let data = try await selection.loadTransferable(type: Data.self), data.count <= 5 * 1024 * 1024,
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
                try Task.checkCancellation()
                photo = "data:image/png;base64," + encoded.base64EncodedString()
            } catch is CancellationError {
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private enum PhotoError: LocalizedError {
        case invalid
        var errorDescription: String? { "Choose a readable photo up to 5 MB and 40 megapixels." }
    }
}
