import AVFoundation
import Foundation
import PhotosUI
import SwiftUI
import VisionKit

private struct NextImportedContact: Decodable {
    let address: String
    let name: String
    let exists: Bool
    let public_key_matches: Bool
    let additional_services: [String]
}

struct NextContactImport: View {
    let base: URL
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var name = ""
    @State private var draft: NextImportedContact?
    @State private var photo: PhotosPickerItem?
    @State private var scanning = false
    @State private var busy = false
    @State private var saved = false
    @State private var error = ""
    @State private var discard = false
    @FocusState private var naming: Bool

    var body: some View {
        NavigationStack {
            Form {
                if !error.isEmpty {
                    Section { Text(error).foregroundStyle(.red).accessibilityIdentifier("next-contact-import-error") }
                }
                if saved {
                    Section { Label("Contact saved. You can find it in Reticulum Contacts.", systemImage: "checkmark.circle") }
                }
                if let draft {
                    Section("Review Reticulum contact") {
                        if draft.exists {
                            Text("Already saved as \(draft.name)")
                        } else {
                            TextField("Contact name", text: $name).focused($naming)
                                .accessibilityIdentifier("next-contact-import-name")
                                .submitLabel(.done).onSubmit { naming = false }
                        }
                        Text(draft.address).font(.caption.monospaced()).textSelection(.enabled)
                            .accessibilityIdentifier("next-contact-import-address")
                        if draft.public_key_matches { Text("The public key matches this address.").font(.caption) }
                        if !draft.additional_services.isEmpty {
                            Text("This adds Reticulum messaging. Other contact methods are managed in their service menus.").font(.caption)
                        }
                    }
                    if !saved {
                        Button("Choose another code") { discard = true }.disabled(busy)
                    }
                } else {
                    Section {
                        Text("Scan the other device’s Reticulum contact code, choose its QR image, or paste a code. Review the name and address before saving.")
                        if DataScannerViewController.isSupported {
                            Button("Scan QR code", systemImage: "camera") { Task { await openCamera() } }.disabled(busy)
                        }
                        PhotosPicker(selection: $photo, matching: .images) {
                            Label("Choose QR image", systemImage: "photo")
                        }.disabled(busy).accessibilityIdentifier("next-contact-import-photo")
                        PasteButton(payloadType: String.self) { values in
                            guard !busy else { return }
                            guard values.count == 1, let value = values.first else {
                                error = "Paste one Reticulum contact code."; return
                            }
                            Task { await preview(value) }
                        }.disabled(busy).accessibilityIdentifier("next-contact-import-paste")
                    }
                }
                if busy { ProgressView("Reading contact code…") }
            }
            .navigationTitle("Add Reticulum contact")
            .accessibilityIdentifier("next-contact-import-form")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(saved ? "Done" : "Cancel") { dismiss() }.disabled(busy) }
                ToolbarItem(placement: .confirmationAction) {
                    if let draft, !draft.exists {
                        Button("Save contact") { Task { await save() } }
                            .disabled(busy || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            .accessibilityIdentifier("next-contact-import-save")
                    }
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer(); Button("Done typing") { naming = false; FamilyKeyboard.dismiss() }
                }
            }
            .confirmationDialog("Discard this contact draft?", isPresented: $discard, titleVisibility: .visible) {
                Button("Choose another code", role: .destructive) { draft = nil; code = ""; name = ""; error = "" }
            }
            .onChange(of: photo) {
                guard let photo, !busy else { return }
                busy = true
                Task {
                    do {
                        let value = try await FamilyQRImage.read(photo)
                        busy = false; self.photo = nil
                        await preview(value)
                    } catch {
                        busy = false; self.photo = nil; self.error = error.localizedDescription
                    }
                }
            }
            .sheet(isPresented: $scanning) {
                NavigationStack {
                    FamilyQRScanner { value in
                        scanning = false
                        Task { await preview(value) }
                    } onError: {
                        scanning = false; error = "The camera couldn’t read a code. Choose a QR image instead."
                    }
                    .overlay(alignment: .top) {
                        Text("Point the camera at one contact QR code.")
                            .padding().background(.regularMaterial).padding()
                    }
                    .navigationTitle("Scan contact code")
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { scanning = false } } }
                }
            }
            .interactiveDismissDisabled(busy)
        }
    }

    @MainActor private func openCamera() async {
        guard !busy else { return }
        busy = true; defer { busy = false }
        let allowed: Bool
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: allowed = true
        case .notDetermined: allowed = await AVCaptureDevice.requestAccess(for: .video)
        default: allowed = false
        }
        guard allowed else {
            error = "Allow camera access in iOS Settings, or choose a QR image instead."; return
        }
        guard DataScannerViewController.isAvailable else {
            error = "Camera scanning is unavailable. Choose a QR image instead."; return
        }
        error = ""; scanning = true
    }

    @MainActor private func request(_ action: String, _ body: [String: String]) async throws -> NextImportedContact {
        struct Token: Decodable { let csrf_token: String }
        let (tokenData, tokenResponse) = try await NextHTTP.shared.data(from: URL(string: "/api/v1/auth/csrf", relativeTo: base)!)
        guard (tokenResponse as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.userAuthenticationRequired) }
        let token = try JSONDecoder().decode(Token.self, from: tokenData)
        var request = URLRequest(url: URL(string: "/api/v1/preview/contact-import/" + action, relativeTo: base)!)
        request.httpMethod = "POST"
        request.setValue(token.csrf_token, forHTTPHeaderField: "X-CSRF-Token")
        request.setValue("http://127.0.0.1:\(base.port!)", forHTTPHeaderField: "Origin")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await NextHTTP.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            let message = (try? JSONSerialization.jsonObject(with: data) as? [String: String])?["message"]
            throw NSError(domain: "neXt contact import", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: message ?? "The contact could not be read or saved."])
        }
        return try JSONDecoder().decode(NextImportedContact.self, from: data)
    }
    @MainActor private func preview(_ value: String) async {
        guard !busy, draft == nil else { return }
        busy = true; error = ""; defer { busy = false }
        do { let result = try await request("preview", ["code": value]); code = value; draft = result; name = result.name }
        catch { self.error = error.localizedDescription }
    }
    @MainActor private func save() async {
        guard !busy, draft?.exists == false else { return }
        naming = false; FamilyKeyboard.dismiss(); busy = true; error = ""; defer { busy = false }
        do { draft = try await request("save", ["code": code, "name": name]); saved = true }
        catch { self.error = error.localizedDescription }
    }
}
