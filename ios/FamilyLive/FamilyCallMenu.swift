import SwiftUI

struct FamilyCallMenu: View {
    @ObservedObject var family: FamilyModel
    @ObservedObject private var sip = FamilySIP.shared
    let contactID: Int
    @State private var routes: [FamilyCallRoute] = []
    @State private var method = "auto"
    @State private var loading = true
    @State private var starting = false
    @State private var visible = false

    private var contact: FamilyContact? { family.state?.contacts?.first { $0.id == contactID } }
    private var selected: FamilyCallRoute? {
        method == "auto" ? routes.first(where: \.automatic) : routes.first { $0.service == method }
    }
    private var refreshKey: String {
        "\(sip.registered)|\(family.state?.voice?.ready == true)|\(family.state?.tcpSession ?? "")"
    }

    var body: some View {
        Form {
            if let contact {
                Section {
                    FamilyContactAvatar(name: contact.name, photo: contact.photo)
                    Text(contact.name).font(.title2)
                    Picker("Connection", selection: $method) {
                        Text("Automatic").tag("auto")
                        ForEach(routes) { route in Text(route.name).tag(route.service) }
                    }
                    if loading { ProgressView("Checking calling methods") }
                    else if let selected {
                        Text("\(selected.name) · \(selected.reason)").font(.footnote)
                    } else { Text("No automatic calling method is available. You can try another method or send a message.") }
                    Button("Call \(contact.name)", systemImage: "phone.fill") { startCall() }
                        .buttonStyle(.borderedProminent)
                        .disabled(loading || starting || selected == nil || family.hasCallInProgress)
                } footer: {
                    Text("Automatic uses available methods and recent call measurements. Methods without recent measurements are marked accordingly.")
                }
            } else { ContentUnavailableView("Contact is no longer approved", systemImage: "person.crop.circle.badge.xmark") }
            if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
        }
        .navigationTitle("Call")
        .onAppear { visible = true }
        .onDisappear { visible = false }
        .task(id: refreshKey) {
            loading = true
            routes = await family.rankedCallRoutes(contactID: contactID)
            if method != "auto" && !routes.contains(where: { $0.service == method }) { method = "auto" }
            loading = false
        }
    }

    private func startCall() {
        starting = true
        Task {
            defer { starting = false }
            routes = await family.rankedCallRoutes(contactID: contactID)
            guard visible, !Task.isCancelled, let contact, let selected, !family.hasCallInProgress else { return }
            if selected.service == "sip" { await sip.call(contact) }
            else { await family.call(contact, automatic: method == "auto") }
        }
    }
}
