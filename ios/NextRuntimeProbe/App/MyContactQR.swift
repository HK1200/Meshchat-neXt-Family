import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI

struct NextFamilyCard {
    private struct Response: Decodable { let contact_card: String }
    private struct Contact: Decodable {
        let format: String
        let version: Int
        let name: String
        let addresses: [String: String]
        let identityPublicKey: String
    }
    static func payload(from data: Data, expectedAddress: String) throws -> String {
        guard data.count <= 16384 else { throw URLError(.cannotParseResponse) }
        let text = try JSONDecoder().decode(Response.self, from: data).contact_card
        guard text.utf8.count <= 8192, let raw = text.data(using: .utf8),
              let dictionary = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
              Set(dictionary.keys).isSubset(of: ["format", "version", "name", "addresses", "identityPublicKey"]) else {
            throw URLError(.cannotParseResponse)
        }
        let card = try JSONDecoder().decode(Contact.self, from: raw)
        guard card.format == "next-family-contact", card.version == 1,
              !card.name.isEmpty, card.name.count <= 64,
              card.addresses["lxmf"] == expectedAddress.lowercased(),
              card.addresses["lxmf"]?.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              Set(card.addresses.keys).isSubset(of: ["lxmf", "lxst"]),
              card.identityPublicKey.range(of: "^[a-f0-9]{128}$", options: .regularExpression) != nil else {
            throw URLError(.cannotParseResponse)
        }
        if let voice = card.addresses["lxst"], voice.range(of: "^[a-f0-9]{32}$", options: .regularExpression) == nil {
            throw URLError(.cannotParseResponse)
        }
        return text
    }
}

struct NextMyContactQR: View {
    private enum Format: Hashable { case lxmf, family }
    let address: String
    let base: URL?
    @Environment(\.dismiss) private var dismiss
    @State private var format: Format = .lxmf
    @State private var familyPayload: String?
    @State private var loading = false
    @State private var error = ""

    private var payload: String? {
        guard address.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil else { return nil }
        return format == .lxmf ? "lxmf://" + address.lowercased() : familyPayload
    }
    private var image: UIImage? {
        guard let payload else { return nil }
        let generator = CIFilter.qrCodeGenerator()
        generator.message = Data(payload.utf8)
        generator.correctionLevel = "M"
        guard let output = generator.outputImage,
              let bitmap = CIContext().createCGImage(output, from: output.extent) else { return nil }
        return UIImage(cgImage: bitmap)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    Picker("Contact code format", selection: $format) {
                        Text("Reticulum messaging").tag(Format.lxmf)
                        Text("Family contact").tag(Format.family)
                    }
                    .pickerStyle(.segmented)
                    .accessibilityIdentifier("my-contact-code-format")
                    if let image, let payload {
                        Image(uiImage: image)
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 240, height: 240)
                            .padding(24)
                            .background(.white)
                            .accessibilityLabel(format == .lxmf ? "Reticulum messaging contact QR code" : "Family Reticulum contact QR code")
                            .accessibilityIdentifier(format == .lxmf ? "my-lxmf-qr-image" : "my-family-qr-image")
                        Text(format == .lxmf
                             ? "Scan this code on the other device to add your Reticulum messaging address. In Family, use Guardian settings to review and approve the contact."
                             : "In Family, scan this code in Guardian settings to add your device name and Reticulum messaging address. It also adds your voice address when Reticulum calling is enabled. The guardian reviews and approves the contact.")
                            .multilineTextAlignment(.center)
                        Text(address)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                        ShareLink(item: payload) {
                            Label("Share contact code", systemImage: "square.and.arrow.up")
                        }
                    } else if loading {
                        ProgressView("Preparing contact card…")
                    } else {
                        ContentUnavailableView("Contact code unavailable", systemImage: "qrcode",
                            description: Text(error.isEmpty ? "Wait for your Reticulum identity, then try again." : error))
                        if format == .family {
                            Button("Try again") { Task { await loadFamilyCard() } }
                        }
                    }
                }
                .padding()
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("My contact QR")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .task(id: format) {
                if format == .family { await loadFamilyCard() }
            }
        }
    }

    @MainActor private func loadFamilyCard() async {
        familyPayload = nil; error = ""; loading = true
        defer { if !Task.isCancelled { loading = false } }
        do {
            guard let base, var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
                throw URLError(.notConnectedToInternet)
            }
            components.path = "/api/v1/preview/contact-card"
            components.query = nil; components.fragment = nil
            guard let endpoint = components.url else { throw URLError(.badURL) }
            let (data, response) = try await NextHTTP.shared.data(from: endpoint)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            let card = try NextFamilyCard.payload(from: data, expectedAddress: address)
            guard !Task.isCancelled else { return }
            familyPayload = card
        } catch {
            guard !Task.isCancelled else { return }
            self.error = "The contact card could not be loaded. Your plain Reticulum messaging code is still available."
        }
    }
}
