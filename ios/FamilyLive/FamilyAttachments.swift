import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import UIKit

struct FamilyDraftAttachment: Identifiable {
    static let limit = 9_950_000
    let id = UUID()
    let name: String
    let data: Data
    let image: String?
}

struct FamilyAttachmentComposer: View {
    @Binding var attachments: [FamilyDraftAttachment]
    @State private var pickingFiles = false
    @State private var photos: [PhotosPickerItem] = []
    @State private var quality = "High"
    @State private var preparing = false
    @State private var error = ""

    var body: some View {
        Button("Attach files", systemImage: "paperclip") { pickingFiles = true }
            .disabled(preparing)
            .fileImporter(isPresented: $pickingFiles, allowedContentTypes: [.data], allowsMultipleSelection: true) { result in
                Task { await addFiles(result) }
            }
        Picker("Photo quality", selection: $quality) {
            ForEach(["Low", "Medium", "High", "Original"], id: \.self) { Text($0) }
        }
        PhotosPicker(selection: $photos, maxSelectionCount: 32, matching: .images) {
            Label("Add photos", systemImage: "photo.on.rectangle")
        }
        .disabled(preparing)
        .onChange(of: photos) {
            let selected = photos
            guard !selected.isEmpty else { return }
            photos = []
            Task { await addPhotos(selected, quality: quality) }
        }
        ForEach(attachments) { item in
            HStack {
                if item.image != nil, let thumbnail = UIImage(data: item.data) {
                    Image(uiImage: thumbnail).resizable().scaledToFit().frame(width: 45, height: 45)
                }
                Text(item.name)
                Spacer()
                Button("Remove", systemImage: "xmark.circle") {
                    attachments.removeAll { $0.id == item.id }
                }
                .buttonStyle(.borderless)
            }
        }
        if preparing { ProgressView("Preparing attachments") }
        if !error.isEmpty { Text(error).foregroundStyle(.red) }
    }

    @MainActor
    private func addFiles(_ result: Result<[URL], Error>) async {
        preparing = true
        error = ""
        defer { preparing = false }
        do {
            for url in try result.get() {
                let attachment = try await Task.detached(priority: .utility) {
                    let scoped = url.startAccessingSecurityScopedResource()
                    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                    let metadata = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                    guard metadata.isRegularFile == true, let size = metadata.fileSize,
                          (1...FamilyDraftAttachment.limit).contains(size) else { throw CocoaError(.fileReadTooLarge) }
                    return FamilyDraftAttachment(name: url.lastPathComponent, data: try Data(contentsOf: url), image: nil)
                }.value
                try append(attachment)
            }
        } catch {
            self.error = "Choose files up to 9.95 MB each."
        }
    }

    @MainActor
    private func addPhotos(_ selected: [PhotosPickerItem], quality: String) async {
        preparing = true
        error = ""
        defer { preparing = false }
        do {
            for photo in selected {
                guard let original = try await photo.loadTransferable(type: Data.self) else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                let kind = photo.supportedContentTypes.first(where: { $0.conforms(to: .image) })?.preferredFilenameExtension ?? "jpg"
                let sequence = attachments.count + 1
                if quality == "Original" {
                    try append(FamilyDraftAttachment(name: "Photo \(sequence).\(kind)", data: original, image: kind))
                } else {
                    guard let image = UIImage(data: original) else { throw CocoaError(.fileReadCorruptFile) }
                    let preset: (CGFloat, CGFloat)
                    switch quality {
                    case "Low": preset = (320, 0.2)
                    case "Medium": preset = (640, 0.6)
                    default: preset = (1280, 0.75)
                    }
                    let scale = min(1, preset.0 / max(image.size.width, image.size.height))
                    let size = CGSize(width: max(1, image.size.width * scale), height: max(1, image.size.height * scale))
                    let format = UIGraphicsImageRendererFormat()
                    format.scale = 1
                    let resized = UIGraphicsImageRenderer(size: size, format: format).jpegData(withCompressionQuality: preset.1) { _ in
                        image.draw(in: CGRect(origin: .zero, size: size))
                    }
                    try append(FamilyDraftAttachment(name: "Photo \(sequence).jpg", data: resized, image: "jpeg"))
                }
            }
        } catch {
            self.error = "Couldn’t prepare a photo. Try a lower quality or a different image."
        }
    }

    private func append(_ attachment: FamilyDraftAttachment) throws {
        guard attachments.count < 32, (1...FamilyDraftAttachment.limit).contains(attachment.data.count) else {
            throw CocoaError(.fileReadTooLarge)
        }
        attachments.append(attachment)
    }
}

struct FamilyReceivedAttachment: View {
    @ObservedObject var family: FamilyModel
    let contactID: Int
    let messageID: String
    let index: Int
    let item: FamilyMessageAttachment
    @State private var url: URL?
    @State private var preview: UIImage?
    @State private var error = ""

    var body: some View {
        if let preview { Image(uiImage: preview).resizable().scaledToFit().frame(maxHeight: 260) }
        if let url { ShareLink(item: url) { Label(item.name, systemImage: "square.and.arrow.up") } }
        else {
            Button(item.name, systemImage: item.image == nil ? "paperclip" : "photo") {
                Task {
                    do {
                        let source = try await family.attachmentURL(contactID: contactID, messageID: messageID, index: index)
                        let destination = try await Task.detached(priority: .utility) {
                            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
                            let destination = folder.appendingPathComponent(item.name)
                            try FileManager.default.copyItem(at: source, to: destination)
                            return destination
                        }.value
                        url = destination
                        if item.image != nil, item.size <= FamilyDraftAttachment.limit {
                            preview = UIImage(contentsOfFile: destination.path)
                        }
                    } catch { self.error = error.localizedDescription }
                }
            }
        }
        if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.red) }
    }
}

struct FamilyIncomingLimitSettings: View {
    @ObservedObject var family: FamilyModel
    @State private var selected = 10_000_000
    @State private var custom = 10.0
    @State private var saved = false
    private let presets = [1_000_000, 10_000_000, 25_000_000, 50_000_000, 1_000_000_000]

    var body: some View {
        Form {
            if family.unlocked {
                Picker("Direct receive limit", selection: $selected) {
                    ForEach(presets, id: \.self) { bytes in
                        Text(bytes == 1_000_000_000 ? "1 GB" : "\(bytes / 1_000_000) MB").tag(bytes)
                    }
                    Text("Custom").tag(0)
                }
                if selected == 0 {
                    TextField("Custom size in MB", value: $custom, format: .number).keyboardType(.decimalPad)
                }
                Button(saved ? "Limit saved" : "Save limit") {
                    let bytes = selected == 0 ? Int((custom * 1_000_000).rounded()) : selected
                    Task { saved = await family.setIncomingDeliveryLimit(bytes) }
                }
                .disabled(selected == 0 && (!custom.isFinite || !(0.001...1000).contains(custom)))
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
        }
        .navigationTitle("Incoming message size")
        .onAppear {
            let bytes = family.state?.incomingDeliveryLimit ?? 10_000_000
            selected = presets.contains(bytes) ? bytes : 0
            custom = Double(bytes) / 1_000_000
        }
    }
}
