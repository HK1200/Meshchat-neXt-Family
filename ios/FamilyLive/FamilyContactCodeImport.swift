import PhotosUI
import SwiftUI
import VisionKit

/// Only supported, nonempty service addresses replace fields in an existing contact.
enum FamilyContactAddressMerge {
    static func apply(_ incoming: [String: String], to existing: [String: String]) -> [String: String] {
        var result = existing
        for service in ["lxmf", "lxst", "meshcore", "sip"] {
            if let value = incoming[service]?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty {
                result[service] = value
            }
        }
        return result
    }
}

struct FamilyContactCodeImport: View {
    @ObservedObject var family: FamilyModel
    let imported: (FamilyContactCard) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var scanning = false
    @State private var photo: PhotosPickerItem?
    @State private var reading = false
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Scan the other device’s contact code, or choose a screenshot. You can review the service addresses before saving the contact.")
                    if DataScannerViewController.isSupported && DataScannerViewController.isAvailable {
                        Button("Scan QR code", systemImage: "camera") { scanning = true }
                            .disabled(reading)
                    }
                    PhotosPicker(selection: $photo, matching: .images) {
                        Label("Choose QR image", systemImage: "photo")
                    }.disabled(reading)
                    if reading { ProgressView("Reading contact code") }
                    if !error.isEmpty { Text(error).foregroundStyle(.red).accessibilityIdentifier("contact-code-error") }
                }
            }
            .navigationTitle("Add contact services")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .onChange(of: photo) {
                guard let selected = photo, !reading else { return }
                reading = true
                Task {
                    defer { reading = false; photo = nil }
                    do { await read(try await FamilyQRImage.read(selected)) }
                    catch { self.error = error.localizedDescription }
                }
            }
            .onChange(of: family.unlocked) { if !family.unlocked { dismiss() } }
            .sheet(isPresented: $scanning) {
                NavigationStack {
                    FamilyQRScanner { payload in
                        scanning = false
                        reading = true
                        Task { await read(payload); reading = false }
                    } onError: {
                        scanning = false
                        error = "The camera couldn’t start. Choose a QR image instead."
                    }
                    .navigationTitle("Scan contact code")
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { scanning = false } } }
                }
            }
        }
    }

    @MainActor private func read(_ payload: String) async {
        guard family.unlocked else { return }
        guard let card = await family.readContactCard(payload), family.unlocked else {
            error = family.error
            return
        }
        imported(card)
        dismiss()
    }
}
