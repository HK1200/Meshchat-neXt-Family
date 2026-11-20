import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI

struct NextMyContactQR: View {
    let address: String
    @Environment(\.dismiss) private var dismiss

    private var payload: String { "lxmf://" + address.lowercased() }

    private var image: UIImage? {
        guard address.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil else { return nil }
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
                    if let image {
                        Image(uiImage: image)
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 240, height: 240)
                            .padding(24)
                            .background(.white)
                            .accessibilityLabel("Reticulum messaging contact QR code")
                            .accessibilityIdentifier("my-lxmf-qr-image")
                        Text("Scan this code on the other device to add your Reticulum messaging address. In Family, use Guardian settings to review and approve the contact.")
                            .multilineTextAlignment(.center)
                        Text(address)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                        ShareLink(item: payload) {
                            Label("Share contact code", systemImage: "square.and.arrow.up")
                        }
                    } else {
                        ContentUnavailableView("Contact code unavailable", systemImage: "qrcode",
                            description: Text("Wait for your Reticulum identity, then try again."))
                    }
                }
                .padding()
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("My contact QR")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }
}
