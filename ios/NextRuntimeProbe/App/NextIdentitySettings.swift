// SPDX-License-Identifier: 0BSD
import SwiftUI
import UniformTypeIdentifiers

private struct NextIdentityDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.data] }
    let bytes: Data
    init(_ key: NextIdentityRecovery.Key) { bytes = key.bytes }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw NextIdentityRecovery.Failure.invalidKey }
        bytes = try NextIdentityRecovery.Key(data).bytes
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: bytes)
    }
}

struct NextIdentitySettings: View {
    @Environment(\.dismiss) private var dismiss
    @State private var status: NextIdentityRecovery.Status?
    @State private var candidate: NextIdentityRecovery.Key?
    @State private var document: NextIdentityDocument?
    @State private var importing = false
    @State private var exporting = false
    @State private var confirmExport = false
    @State private var confirmRestore = false
    @State private var error = ""
    @State private var notice = ""
    var body: some View {
        NavigationStack {
            Form {
                Section("Your Reticulum identity") {
                    if let current = status?.current {
                        Text(current.messagingAddress).font(.caption.monospaced()).textSelection(.enabled)
                            .accessibilityIdentifier("next-identity-current-address")
                        Button("Save identity backup") { confirmExport = true }
                            .accessibilityIdentifier("next-identity-export")
                    } else {
                        Text("No saved identity is available yet.")
                    }
                    Text("An identity backup restores your Reticulum addresses. It does not include messages, settings, SIP passwords or radio pairing.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Restore an identity") {
                    Button("Choose identity file") { importing = true }
                        .accessibilityIdentifier("next-identity-import")
                    Text("Choose a standard Reticulum private identity file, such as identity.bin. A public contact address or QR code cannot restore an identity.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if let pending = status?.pending {
                        Text("Restore ready: \(pending.messagingAddress)")
                            .accessibilityIdentifier("next-identity-pending-address")
                        Text("Close neXt from the app switcher, then open it again to use this identity. Locking the screen does not restart the app. Existing conversations stay on this device with their original identity.")
                    }
                    if let problem = status?.pendingError { Text(problem).foregroundStyle(.red) }
                    if status?.pending != nil || status?.pendingError != nil {
                        Button("Cancel pending restore", role: .destructive) {
                            perform { try NextIdentityRecovery.cancel(support: NextIdentityRecovery.support()); notice = "Restore canceled." }
                        }.accessibilityIdentifier("next-identity-cancel")
                    }
                }
                if let saved = status?.saved, !saved.isEmpty {
                    Section("Previous identities on this device") {
                        ForEach(saved, id: \.hash) { key in
                            Button { candidate = key; confirmRestore = true } label: {
                                VStack(alignment: .leading) {
                                    Text("Restore previous identity")
                                    Text(key.messagingAddress).font(.caption.monospaced())
                                }
                            }
                        }
                        Text("neXt keeps the previous private key before a restore, so you can return to its saved conversations.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if let problem = status?.savedError { Section { Text(problem).foregroundStyle(.red) } }
                if !notice.isEmpty { Section { Text(notice).accessibilityIdentifier("next-identity-notice") } }
                if !error.isEmpty {
                    Section {
                        Text(error).foregroundStyle(.red).accessibilityIdentifier("next-identity-error")
                        Button("Cancel any pending restore") {
                            perform { try NextIdentityRecovery.cancel(support: NextIdentityRecovery.support()); notice = "Pending restore canceled." }
                        }
                    }
                }
            }
            .accessibilityIdentifier("next-identity-form")
            .navigationTitle("Identity backup")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { reload() }
            .confirmationDialog("Save your private identity?", isPresented: $confirmExport, titleVisibility: .visible) {
                Button("Save private identity file") {
                    perform {
                        guard let current = try NextIdentityRecovery.status(support: NextIdentityRecovery.support()).current else {
                            throw NextIdentityRecovery.Failure.unavailable
                        }
                        document = NextIdentityDocument(current)
                        exporting = true
                    }
                }
            } message: {
                Text("Anyone with this file can use your Reticulum identity. Save it somewhere private; do not send it as a contact card.")
            }
            .fileExporter(isPresented: $exporting, document: document, contentType: .data,
                          defaultFilename: "neXt-identity-\(status?.current?.hash ?? "backup").bin") { result in
                document = nil
                switch result {
                case .success: notice = "Identity backup saved."; error = ""
                case .failure(let problem): report(problem)
                }
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.data]) { result in
                switch result {
                case .success(let file):
                    let scoped = file.startAccessingSecurityScopedResource()
                    defer { if scoped { file.stopAccessingSecurityScopedResource() } }
                    perform { candidate = try NextIdentityRecovery.importFile(file); confirmRestore = true }
                case .failure(let problem): report(problem)
                }
            }
            .alert("Restore this identity?", isPresented: $confirmRestore, presenting: candidate) { key in
                Button("Restore after restart", role: .destructive) {
                    candidate = nil
                    perform {
                        let staged = try NextIdentityRecovery.stage(key, support: NextIdentityRecovery.support())
                        notice = staged ? "Restore prepared. Close and reopen neXt to use it." : "This identity is already active."
                    }
                }
                Button("Cancel", role: .cancel) { candidate = nil }
            } message: { key in
                Text("Messaging address: \(key.messagingAddress)\n\nYour current identity is kept on this device before switching. Existing messages remain with their original identity. The change takes effect only after closing and reopening neXt.")
            }
        }
    }
    private func report(_ problem: Error) {
        let value = problem as NSError
        if value.domain == NSCocoaErrorDomain && value.code == NSUserCancelledError { return }
        error = problem.localizedDescription
    }
    private func reload() {
        do { status = try NextIdentityRecovery.status(support: NextIdentityRecovery.support()); error = "" }
        catch { self.error = error.localizedDescription }
    }
    private func perform(_ action: () throws -> Void) {
        do { try action(); reload() }
        catch { self.error = error.localizedDescription }
    }
}
