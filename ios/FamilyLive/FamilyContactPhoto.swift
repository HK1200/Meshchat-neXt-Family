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
                guard let data = try await selection.loadTransferable(type: Data.self) else {
                    throw FamilyContactPhotoCodec.PhotoError.invalid
                }
                let encoded = try FamilyContactPhotoCodec.encode(data)
                try Task.checkCancellation()
                photo = encoded
            } catch is CancellationError {
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

}
