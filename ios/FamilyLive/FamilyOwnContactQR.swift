import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI

struct FamilyOwnContactQR: View {
    @ObservedObject var family: FamilyModel
    @State private var code: UIImage?
    @State private var payload: String?
    @State private var error: String?

    var body: some View {
        ScrollView {
            if family.unlocked {
                VStack(spacing: 16) {
                    if let code, let payload {
                        Image(uiImage: code)
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(maxWidth: 320)
                            .padding(20)
                            .background(.white)
                            .accessibilityLabel("My contact QR code")
                        Text("On the other device, open Guardian settings and scan this code to review the contact.")
                            .multilineTextAlignment(.center)
                        if let address = family.state?.address, !address.isEmpty {
                            Text(address)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                        }
                        ShareLink(item: payload) { Label("Share contact code", systemImage: "square.and.arrow.up") }
                    } else if let error {
                        Text(error)
                        Button("Try again") { Task { await loadCode() } }
                    } else {
                        ProgressView("Preparing contact QR")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding()
                .task { await loadCode() }
            }
        }
        .navigationTitle("My contact QR")
    }

    private func loadCode() async {
        error = nil
        do {
            guard let text = try await family.ownContactCard() else { return }
            let generator = CIFilter.qrCodeGenerator()
            generator.message = Data(text.utf8)
            generator.correctionLevel = "M"
            guard let output = generator.outputImage,
                  let bitmap = CIContext().createCGImage(output, from: output.extent) else {
                error = "Could not generate the contact QR."
                return
            }
            code = UIImage(cgImage: bitmap)
            payload = text
        } catch {
            self.error = error.localizedDescription
        }
    }
}
