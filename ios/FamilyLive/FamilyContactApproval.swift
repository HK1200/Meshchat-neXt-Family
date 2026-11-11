import PhotosUI
import SwiftUI
import VisionKit

struct FamilyContactApproval: View {
    @ObservedObject var family: FamilyModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var address = ""
    @State private var contactSaved = false
    @State private var importedCard: FamilyContactCard?
    @State private var qrPhoto: PhotosPickerItem?
    @State private var showingQRScanner = false
    @State private var readingQR = false

    var body: some View {
        Form {
            if family.unlocked {
                Section("Approve contact") {
                    TextField("Contact name", text: $name)
                        .accessibilityIdentifier("contact-name")
                    TextField("LXMF address", text: $address).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .accessibilityIdentifier("contact-address")
                    NavigationLink("Find messaging client") {
                        FamilyClientDiscovery(family: family) { client in
                            importedCard = nil
                            name = String(client.name.prefix(32))
                            address = client.address
                            contactSaved = false
                        }
                    }
                    if DataScannerViewController.isSupported && DataScannerViewController.isAvailable {
                        Button("Scan contact QR code", systemImage: "camera") { showingQRScanner = true }
                            .disabled(readingQR)
                    }
                    PhotosPicker(selection: $qrPhoto, matching: .images) {
                        Label("Import contact QR image", systemImage: "qrcode")
                    }
                    .disabled(readingQR)
                    .onChange(of: qrPhoto) {
                        guard let photo = qrPhoto else { return }
                        readingQR = true
                        Task { await importQRPhoto(photo) }
                    }
                    if readingQR { ProgressView("Reading contact code") }
                    Button(contactSaved ? "Contact saved" : "Save approved contact") {
                        let approvedAddress = address.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                        let key = importedCard?.addresses["lxmf"]?.lowercased() == approvedAddress
                            ? importedCard?.identityPublicKey : nil
                        Task {
                            contactSaved = await family.saveContact(name: name, address: address, identityPublicKey: key)
                        }
                    }
                    .disabled(readingQR)
                    .onChange(of: name) { contactSaved = false }
                    .onChange(of: address) { contactSaved = false }
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
        }
        .navigationTitle("Approve contact")
        .toolbar { Button("Back to settings") { dismiss() } }
        .sheet(isPresented: $showingQRScanner) {
            NavigationStack {
                FamilyQRScanner { payload in
                    showingQRScanner = false
                    readingQR = true
                    Task {
                        await importQRPayload(payload)
                        readingQR = false
                    }
                } onError: {
                    showingQRScanner = false
                    family.error = "The camera couldn’t start. You can import a QR image instead."
                }
                .navigationTitle("Scan contact QR code")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { showingQRScanner = false }
                    }
                }
            }
        }
    }

    private func importQRPayload(_ payload: String) async {
        guard let card = await family.readContactCard(payload), let lxmf = card.addresses["lxmf"] else { return }
        importedCard = card
        name = card.name ?? ""
        address = lxmf
        contactSaved = false
    }

    private func importQRPhoto(_ photo: PhotosPickerItem) async {
        defer {
            qrPhoto = nil
            readingQR = false
        }
        do {
            let payload = try await FamilyQRImage.read(photo)
            guard family.unlocked else { return }
            await importQRPayload(payload)
        } catch {
            if family.unlocked { family.error = error.localizedDescription }
        }
    }
}
