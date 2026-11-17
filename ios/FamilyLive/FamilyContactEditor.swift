import SwiftUI

struct FamilyContactEditor: View {
    @ObservedObject var family: FamilyModel
    let contact: FamilyContact
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var address = ""
    @State private var voiceAddress = ""
    @State private var meshcoreAddress = ""
    @State private var busy = false
    @State private var confirmRemoval = false

    var body: some View {
        Form {
            if family.unlocked {
                TextField("Contact name", text: $name)
                TextField("LXMF address", text: $address).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("Reticulum voice address", text: $voiceAddress)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("MeshCore public key", text: $meshcoreAddress)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                if contact.addresses["lxmf"]?.isEmpty == false {
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
                        if await family.saveContact(id: contact.id, name: name, address: address, voiceAddress: voiceAddress, meshcoreAddress: meshcoreAddress) { dismiss() }
                        busy = false
                    }
                }
                .disabled(busy || name.isEmpty || (address.isEmpty && voiceAddress.isEmpty && meshcoreAddress.isEmpty))
                Button("Remove contact approval", role: .destructive) { confirmRemoval = true }.disabled(busy)
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
        }
        .navigationTitle("Edit contact")
        .onAppear {
            name = contact.name
            address = contact.addresses["lxmf"] ?? ""
            voiceAddress = contact.addresses["lxst"] ?? ""
            meshcoreAddress = contact.addresses["meshcore"] ?? ""
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
