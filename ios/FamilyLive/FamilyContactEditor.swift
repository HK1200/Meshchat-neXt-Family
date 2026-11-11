import SwiftUI

struct FamilyContactEditor: View {
    @ObservedObject var family: FamilyModel
    let contact: FamilyContact
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var address = ""
    @State private var voiceAddress = ""
    @State private var busy = false
    @State private var confirmRemoval = false

    var body: some View {
        Form {
            if family.unlocked {
                TextField("Contact name", text: $name)
                TextField("LXMF address", text: $address).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("Reticulum voice address", text: $voiceAddress)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                if contact.addresses["lxmf"]?.isEmpty == false {
                    Button("Find voice address from approved messaging identity") {
                        Task {
                            if let resolved = await family.resolveVoiceAddress(contact.id) { voiceAddress = resolved }
                        }
                    }
                }
                Button("Save contact") {
                    busy = true
                    Task {
                        if await family.saveContact(id: contact.id, name: name, address: address, voiceAddress: voiceAddress) { dismiss() }
                        busy = false
                    }
                }
                .disabled(busy || name.isEmpty || (address.isEmpty && voiceAddress.isEmpty))
                Button("Remove contact approval", role: .destructive) { confirmRemoval = true }.disabled(busy)
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
        }
        .navigationTitle("Edit contact")
        .onAppear {
            name = contact.name
            address = contact.addresses["lxmf"] ?? ""
            voiceAddress = contact.addresses["lxst"] ?? ""
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
