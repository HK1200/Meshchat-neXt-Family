import SwiftUI
import WebKit

struct NextExportItem: Identifiable {
    let id = UUID()
    let file: URL
}

struct NextAttachmentExport: View {
    let item: NextExportItem
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Image(systemName: "doc").font(.largeTitle)
                Text(item.file.lastPathComponent).textSelection(.enabled)
                    .accessibilityIdentifier("export-attachment-name")
                ShareLink(item: item.file) { Label(item.file.pathExtension.lowercased() == "mbtiles" ? "Save or share map" : "Save or share attachment", systemImage: "square.and.arrow.up") }
                    .accessibilityIdentifier("share-attachment")
            }
            .padding()
            .navigationTitle(item.file.pathExtension.lowercased() == "mbtiles" ? "Offline map" : "Attachment")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}

@MainActor
final class NextAttachmentDownloads: NSObject, WKDownloadDelegate {
    let base: URL
    let onComplete: (URL) -> Void
    let onError: (String) -> Void
    private var active: WKDownload?
    private var destination: URL?
    private var limit: Int64 = 10_000_000
    private var oversizedMessage: String { limit > 10_000_000 ? "This map exceeds the 2 GB limit." : "This attachment exceeds the 10 MB direct-message limit." }

    init(base: URL, onComplete: @escaping (URL) -> Void, onError: @escaping (String) -> Void) {
        self.base = base; self.onComplete = onComplete; self.onError = onError
        super.init()
    }

    func isLocal(_ url: URL?) -> Bool {
        guard let url else { return false }
        return url.scheme == base.scheme && url.host == base.host && url.port == base.port && url.user == nil && url.password == nil
    }

    func downloadLimit(for url: URL?) -> Int64? {
        guard let url else { return nil }
        if url.scheme == "blob" {
            return isLocal(URL(string: String(url.absoluteString.dropFirst(5)))) ? 10_000_000 : nil
        }
        guard isLocal(url) else { return nil }
        if url.path.range(of: "^/api/v1/lxmf-messages/attachment/[a-f0-9]{64}/(file|image)$", options: .regularExpression) != nil { return 10_000_000 }
        if url.path.range(of: "^/api/v1/map/export/[a-f0-9]{16}/download$", options: .regularExpression) != nil { return 2 * 1024 * 1024 * 1024 }
        return nil
    }

    func allows(_ url: URL?) -> Bool { downloadLimit(for: url) != nil }

    func start(_ download: WKDownload) {
        guard active == nil else { download.cancel { _ in }; return }
        guard let allowed = downloadLimit(for: download.originalRequest.url) else { download.cancel { _ in }; return }
        limit = allowed
        active = download
        download.delegate = self
    }

    func cancel() {
        let cancelled = active
        active = nil
        cancelled?.cancel { _ in }
        if let destination { try? FileManager.default.removeItem(at: destination.deletingLastPathComponent()) }
        destination = nil
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        guard response.expectedContentLength <= limit else {
            completionHandler(nil); cancel(); onError(oversizedMessage); return
        }
        let raw = suggestedFilename.replacingOccurrences(of: "\\", with: "/").components(separatedBy: "/").last ?? "attachment"
        let safe = raw.filter { character in character.unicodeScalars.allSatisfy { !CharacterSet.controlCharacters.contains($0) && !(0x202A...0x202E).contains($0.value) && !(0x2066...0x2069).contains($0.value) } }.trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        let name = safe.isEmpty ? "attachment" : String(safe.prefix(120))
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("next-attachment-" + UUID().uuidString, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let file = folder.appendingPathComponent(name)
            destination = file
            completionHandler(file)
        } catch {
            completionHandler(nil); cancel(); onError("There isn’t enough space to save this attachment.")
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard active === download else { return }
        guard let file = destination else { cancel(); return }
        let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max
        guard Int64(size) <= limit else { cancel(); onError(oversizedMessage); return }
        active = nil; destination = nil
        onComplete(file)
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        guard active === download else { return }
        cancel(); onError("The attachment couldn’t be saved. Please try again.")
    }

    func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse,
                  newRequest request: URLRequest, decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
        decisionHandler(allows(request.url) ? .allow : .cancel)
    }

    func download(_ download: WKDownload, didReceive challenge: URLAuthenticationChallenge,
                  completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(.cancelAuthenticationChallenge, nil)
    }
}
