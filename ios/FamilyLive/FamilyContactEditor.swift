import SwiftUI

struct FamilyContactEditor: View {
    @ObservedObject var family: FamilyModel
    let contact: FamilyContact
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var address = ""
    @State private var voiceAddress = ""
    @State private var meshcoreAddress = ""
    @State private var sipAddress = ""
    @State private var photo: String?
    @State private var photoLoading = false
    @State private var busy = false
    @State private var confirmRemoval = false
    @State private var importingCode = false
    @State private var importedCard: FamilyContactCard?
    @State private var loadedContact = false
    private enum Field: Hashable { case name, lxmf, voice, sip, meshcore }
    @FocusState private var focusedField: Field?

    var body: some View {
        Form {
            if family.unlocked {
                FamilyContactPhotoEditor(name: name, photo: $photo, loading: $photoLoading)
                TextField("Contact name", text: $name)
                    .focused($focusedField, equals: .name)
                    .accessibilityIdentifier("edit-contact-name")
                TextField("LXMF address", text: $address).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .focused($focusedField, equals: .lxmf)
                TextField("Reticulum voice address", text: $voiceAddress)
                    .focused($focusedField, equals: .voice)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("SIP extension or address", text: $sipAddress)
                    .focused($focusedField, equals: .sip)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("MeshCore public key", text: $meshcoreAddress)
                    .focused($focusedField, equals: .meshcore)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("Scan or import service QR code", systemImage: "qrcode.viewfinder") { importingCode = true }
                    .disabled(busy)
                NavigationLink("Find messaging client") {
                    FamilyClientDiscovery(family: family, editingContactID: contact.id) { client in
                        address = client.address
                        importedCard = nil
                    }
                }
                NavigationLink("Find MeshCore contact") {
                    FamilyClientDiscovery(family: family, service: "meshcore", editingContactID: contact.id) { client in
                        meshcoreAddress = client.address
                    }
                }
                Text("Import fills the services in the code. Other services, the name, and the photo stay unchanged. Review the addresses before saving.")
                    .font(.footnote).foregroundStyle(.secondary)
                if contact.addresses["lxmf"]?.isEmpty == false {
                    if contact.addresses["lxst"]?.isEmpty == false {
                        NavigationLink("This contact’s incoming call alerts") {
                            FamilyCallAlertRouteEditor(family: family, contactID: contact.id)
                        }.accessibilityIdentifier("contact-call-alert-route")
                    }
                    NavigationLink("Private mailbox push route") {
                        FamilyMailboxRouteEditor(family: family, contactID: contact.id)
                    }
                    Button("Find voice address from approved messaging identity") {
                        Task {
                            if let resolved = await family.resolveVoiceAddress(contact.id) { voiceAddress = resolved }
                        }
                    }
                }
                Button("Save contact") {
                    busy = true
                    Task {
                        if await family.saveContact(id: contact.id, name: name, address: address, voiceAddress: voiceAddress, identityPublicKey: importedCard?.addresses["lxmf"]?.lowercased() == address.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ? importedCard?.identityPublicKey : nil, meshcoreAddress: meshcoreAddress, sipAddress: sipAddress, photo: photo, replacePhoto: true) { dismiss() }
                        busy = false
                    }
                }
                .disabled(busy || photoLoading || name.isEmpty || (address.isEmpty && voiceAddress.isEmpty && meshcoreAddress.isEmpty && sipAddress.isEmpty))
                Button("Remove contact approval", role: .destructive) { confirmRemoval = true }.disabled(busy)
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
        }
        .accessibilityIdentifier("contact-editor-form")
        .scrollDismissesKeyboard(.interactively)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done typing") { focusedField = nil; FamilyKeyboard.dismiss() }
                    .accessibilityIdentifier("finish-contact-editor-entry")
            }
        }
        .navigationTitle("Edit contact")
        .sheet(isPresented: $importingCode) {
            FamilyContactCodeImport(family: family) { card in
                importedCard = card
                let merged = FamilyContactAddressMerge.apply(card.addresses, to: [
                    "lxmf": address, "lxst": voiceAddress, "meshcore": meshcoreAddress, "sip": sipAddress
                ])
                address = merged["lxmf"] ?? ""
                voiceAddress = merged["lxst"] ?? ""
                meshcoreAddress = merged["meshcore"] ?? ""
                sipAddress = merged["sip"] ?? ""
            }
        }
        .onAppear {
            guard !loadedContact else { return }
            loadedContact = true
            name = contact.name
            address = contact.addresses["lxmf"] ?? ""
            voiceAddress = contact.addresses["lxst"] ?? ""
            meshcoreAddress = contact.addresses["meshcore"] ?? ""
            sipAddress = contact.addresses["sip"] ?? ""
            photo = contact.photo
        }
        .confirmationDialog("Remove approval for \(contact.name)?", isPresented: $confirmRemoval, titleVisibility: .visible) {
            Button("Remove contact approval", role: .destructive) {
                busy = true
                Task {
                    if await family.removeContact(contact.id) { dismiss() }
                    busy = false
                }
            }
        }
    }
}


private struct FamilyMailboxRouteEditor: View {
    @ObservedObject var family: FamilyModel
    let contactID: Int
    @Environment(\.dismiss) private var dismiss
    @State private var provider = ""
    @State private var audience = ""
    @State private var relay = ""
    @State private var hasRoute = false
    @State private var busy = true
    @State private var error = ""

    var body: some View {
        Form {
            if family.unlocked {
                Section {
                    TextField("HTTPS provider", text: $provider)
                        .keyboardType(.URL)
                    TextField("Provider audience", text: $audience)
                    TextField("Reticulum relay address", text: $relay)
                } footer: {
                    Text("Messages to this contact go through the relay. The provider receives a signed hint after the relay confirms transfer. Message text and attachments stay in Reticulum.")
                }
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                Button("Save push route") {
                    save(FamilyMailboxRoute(
                        provider: provider.trimmingCharacters(in: .whitespacesAndNewlines),
                        audience: audience.trimmingCharacters(in: .whitespacesAndNewlines),
                        relay: relay.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                    ))
                }
                .disabled(busy || provider.isEmpty || audience.isEmpty || relay.isEmpty)
                if hasRoute {
                    Button("Remove push route", role: .destructive) { save(nil) }
                        .disabled(busy)
                }
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
            }
        }
        .navigationTitle("Private mailbox push route")
        .task {
            defer { busy = false }
            guard family.unlocked else { return }
            do {
                if let route = try await family.loadMailboxRoute(contactID: contactID) {
                    provider = route.provider
                    audience = route.audience
                    relay = route.relay
                    hasRoute = true
                }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func save(_ route: FamilyMailboxRoute?) {
        guard family.unlocked, !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do {
                try await family.saveMailboxRoute(contactID: contactID, route: route)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
