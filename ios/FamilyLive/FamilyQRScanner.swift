import PhotosUI
import Vision
import SwiftUI
import VisionKit

@MainActor
struct FamilyQRScanner: UIViewControllerRepresentable {
    let onCode: (String) -> Void
    let onError: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onCode: onCode, onError: onError) }

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(
            recognizedDataTypes: [.barcode(symbologies: [.qr])],
            qualityLevel: .balanced,
            recognizesMultipleItems: false,
            isHighlightingEnabled: true
        )
        scanner.delegate = context.coordinator
        Task { @MainActor [weak scanner] in
            do { try scanner?.startScanning() }
            catch { context.coordinator.fail() }
        }
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {}

    static func dismantleUIViewController(_ scanner: DataScannerViewController, coordinator: Coordinator) {
        scanner.stopScanning()
        scanner.delegate = nil
    }

    @MainActor
    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        private let onCode: (String) -> Void
        private let onError: () -> Void
        private var completed = false

        init(onCode: @escaping (String) -> Void, onError: @escaping () -> Void) {
            self.onCode = onCode
            self.onError = onError
        }

        func dataScanner(_ scanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
            guard !completed, case let .barcode(code)? = addedItems.first, let payload = code.payloadStringValue else { return }
            completed = true
            scanner.stopScanning()
            onCode(payload)
        }

        func dataScanner(_ scanner: DataScannerViewController, becameUnavailableWithError error: DataScannerViewController.ScanningUnavailable) {
            fail()
        }

        func fail() {
            guard !completed else { return }
            completed = true
            onError()
        }
    }
}


enum FamilyQRImage {
    private enum ReadError: LocalizedError {
        case unreadable, missing, ambiguous

        var errorDescription: String? {
            switch self {
            case .unreadable: "Couldn’t open the selected image."
            case .missing: "No QR code found in the image."
            case .ambiguous: "Choose an image with one QR code."
            }
        }
    }

    static func read(_ photo: PhotosPickerItem) async throws -> String {
        guard let data = try await photo.loadTransferable(type: Data.self) else { throw ReadError.unreadable }
        return try await Task.detached(priority: .userInitiated) {
            let request = VNDetectBarcodesRequest()
            request.symbologies = [.qr]
            do { try VNImageRequestHandler(data: data).perform([request]) }
            catch { throw ReadError.unreadable }
            let payloads = Set((request.results ?? []).compactMap(\.payloadStringValue))
            guard !payloads.isEmpty else { throw ReadError.missing }
            guard payloads.count == 1, let payload = payloads.first else { throw ReadError.ambiguous }
            return payload
        }.value
    }
}
