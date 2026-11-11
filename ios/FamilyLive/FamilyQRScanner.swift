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
