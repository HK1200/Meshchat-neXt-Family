import CoreLocation
import CryptoKit
import Foundation
import SwiftUI

/// Same published map and integrity checks used by the Android edition.
enum FamilyMapPackage {
    static let url = URL(string: "https://github.com/hk1200/Meshchat-neXt/releases/download/v0.1.0/MeshchatNext-PNW-SouthernBC-detail.mbtiles")!
    static let bytes: Int64 = 108_847_104
    static let digest = "a9b66376fbb9656c4e0ee20ff8c28b29cbd1b98eefaa23ba2a8ad71e4fd692d5"

    static func covers(latitude: Double, longitude: Double) -> Bool {
        (42...53).contains(latitude) && (-128 ... -110).contains(longitude)
    }

    static func verify(_ file: URL, bytes: Int64 = FamilyMapPackage.bytes, digest: String = FamilyMapPackage.digest) throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard (attributes[.size] as? NSNumber)?.int64Value == bytes else { throw DownloadError.verification }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty { hash.update(data: data) }
        guard hash.finalize().map({ String(format: "%02x", $0) }).joined() == digest else {
            throw DownloadError.verification
        }
    }

    enum DownloadError: LocalizedError {
        case verification, response
        var errorDescription: String? {
            switch self {
            case .verification: "The map failed verification. Your existing maps were kept. Please retry."
            case .response: "The map server did not return the map. Please retry later."
            }
        }
    }
}

/// Caps disk use during transfer; verification reads the result in bounded chunks.
private final class FamilyMapTransfer: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        if totalBytesWritten > FamilyMapPackage.bytes || totalBytesExpectedToWrite > FamilyMapPackage.bytes {
            downloadTask.cancel()
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        let host = request.url?.host?.lowercased() ?? ""
        let trusted = host == "github.com" || host.hasSuffix(".githubusercontent.com")
        completionHandler(request.url?.scheme == "https" && trusted ? request : nil)
    }
}

@MainActor
final class FamilyMapDownload: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    @Published private(set) var busy = false
    @Published private(set) var status = ""
    @Published private(set) var locationUnavailable = false
    private let manager = CLLocationManager()
    private var timeout: Task<Void, Never>?
    private var transfer: Task<Void, Never>?
    private var attempt: UUID?
    private var locateCompletion: (() -> Void)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    func findRegion(_ completion: @escaping () -> Void) {
        guard !busy else { return }
        busy = true
        locationUnavailable = false
        status = "Finding your region on this device…"
        locateCompletion = completion
        timeout = Task {
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, locateCompletion != nil else { return }
            locationFailed()
        }
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        default: locationFailed()
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard locateCompletion != nil else { return }
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        case .denied, .restricted: locationFailed()
        default: break
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let completion = locateCompletion, let fix = locations.last,
              fix.horizontalAccuracy >= 0, fix.horizontalAccuracy <= 10_000,
              abs(fix.timestamp.timeIntervalSinceNow) <= 900 else { return }
        finishLocation()
        busy = false
        if FamilyMapPackage.covers(latitude: fix.coordinate.latitude, longitude: fix.coordinate.longitude) {
            status = "Pacific Northwest and southern BC map available."
            completion()
        } else {
            status = "No downloadable pack covers this region yet. Import an MBTiles map below."
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) { locationFailed() }

    private func locationFailed() {
        guard locateCompletion != nil else { return }
        finishLocation()
        busy = false
        locationUnavailable = true
        status = "Couldn’t find your region. You can download the PNW map or import another region."
    }

    private func finishLocation() {
        locateCompletion = nil
        timeout?.cancel(); timeout = nil
        manager.stopUpdatingLocation()
    }

    func cancel() {
        finishLocation()
        attempt = nil
        transfer?.cancel(); transfer = nil
        busy = false
        status = "Map download canceled. Existing maps were kept."
    }

    func download(into family: FamilyModel) {
        guard !busy, family.unlocked else { return }
        let id = UUID()
        attempt = id
        busy = true
        status = "Downloading and verifying the map (104 MiB)…"
        transfer = Task {
            defer { if attempt == id { busy = false; transfer = nil; attempt = nil } }
            let delegate = FamilyMapTransfer()
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForResource = 480
            config.httpShouldSetCookies = false
            config.urlCredentialStorage = nil
            let session = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
            defer { session.invalidateAndCancel() }
            do {
                let (temporary, response) = try await session.download(from: FamilyMapPackage.url)
                defer { try? FileManager.default.removeItem(at: temporary) }
                guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                    throw FamilyMapPackage.DownloadError.response
                }
                try Task.checkCancellation()
                guard attempt == id else { return }
                try await Task.detached(priority: .utility) { try FamilyMapPackage.verify(temporary) }.value
                try Task.checkCancellation()
                guard attempt == id else { return }
                guard family.unlocked else { status = "Unlock Guardian settings to add a map."; return }
                // Give the import a meaningful name, while retaining its existing authorization checks.
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                defer { try? FileManager.default.removeItem(at: folder) }
                let named = folder.appendingPathComponent("PNW and southern BC detail.mbtiles")
                try FileManager.default.moveItem(at: temporary, to: named)
                let installed = await family.importMap(named)
                guard attempt == id else { return }
                status = installed ? "Offline map ready." : family.error
            } catch is CancellationError { if attempt == id { status = "Map download canceled. Existing maps were kept." } }
            catch {
                guard attempt == id else { return }
                status = Task.isCancelled ? "Map download canceled. Existing maps were kept." : error.localizedDescription
            }
        }
    }
}
