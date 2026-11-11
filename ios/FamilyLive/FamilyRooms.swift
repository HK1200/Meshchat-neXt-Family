import PhotosUI
import VisionKit
import SwiftUI

struct FamilyRoomChat: View {
    @ObservedObject var family: FamilyModel
    let room: FamilyRoom
    @State private var draft = ""
    @State private var sending = false

    private var runtime: FamilyRoomState? { family.state?.roomRuntime?[String(room.id)] }

    var body: some View {
        Form {
            Section {
                Text(runtime?.joined == true ? "Joined" : runtime?.status ?? "Connecting")
                if let error = runtime?.error, !error.isEmpty { Text(error).foregroundStyle(.red) }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
            Section("Messages") {
                ForEach(runtime?.messages ?? []) { message in
                    VStack(alignment: .leading) {
                        if let nick = message.nick { Text(nick).font(.headline) }
                        Text(message.text)
                        if message.delivery == "failed" && !room.readOnly {
                            Button("Retry") {
                                Task { _ = await family.perform("room_retry", ["roomId": room.id, "seq": message.seq]) }
                            }
                        }
                    }
                }
            }
            if !room.readOnly {
                Section {
                    TextField("Message", text: $draft)
                    Button("Send") {
                        let text = draft
                        sending = true
                        Task {
                            if await family.perform("room_post", ["roomId": room.id, "text": text]), draft == text {
                                draft = ""
                            }
                            sending = false
                        }
                    }
                    .disabled(sending || runtime?.joined != true || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .navigationTitle(room.name)
        .task { _ = await family.perform("room_open", ["roomId": room.id]) }
        .onDisappear { Task { _ = await family.perform("room_close") } }
    }
}

struct FamilyRoomSettings: View {
    @ObservedObject var family: FamilyModel

    var body: some View {
        Form {
            if family.unlocked {
                if let error = family.state?.roomError, !error.isEmpty { Text(error).foregroundStyle(.red) }
                ForEach(family.state?.rooms ?? []) { room in
                    NavigationLink(room.name) { FamilyRoomEditor(family: family, room: room) }
                }
                NavigationLink("Approve a Relay Chat room") { FamilyRoomEditor(family: family, room: nil) }
            }
        }
        .navigationTitle("Approved rooms")
    }
}

struct FamilyRoomEditor: View {
    @ObservedObject var family: FamilyModel
    let room: FamilyRoom?
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var hub = ""
    @State private var channel = ""
    @State private var password = ""
    @State private var readOnly = false
    @State private var clearPassword = false
    @State private var busy = false
    @State private var confirmRemoval = false
    @State private var qrPhoto: PhotosPickerItem?
    @State private var showingScanner = false

    private var listing: FamilyRoomListing? {
        family.state?.roomDiscovery?.first { $0.hubHash == hub.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
    }

    var body: some View {
        Form {
            if family.unlocked {
                Section {
                    if room == nil {
                        if DataScannerViewController.isSupported && DataScannerViewController.isAvailable {
                            Button("Scan room QR code", systemImage: "camera") { showingScanner = true }.disabled(busy)
                        }
                        PhotosPicker(selection: $qrPhoto, matching: .images) {
                            Label("Import room QR image", systemImage: "qrcode")
                        }
                        .disabled(busy)
                        .onChange(of: qrPhoto) {
                            guard let photo = qrPhoto else { return }
                            busy = true
                            Task {
                                defer { qrPhoto = nil; busy = false }
                                do { await importCard(try await FamilyQRImage.read(photo)) }
                                catch { if family.unlocked { family.error = error.localizedDescription } }
                            }
                        }
                    }
                    TextField("Room display name", text: $name)
                    TextField("Relay Chat hub address", text: $hub).textInputAutocapitalization(.never).autocorrectionDisabled()
                    if let hubs = family.state?.rrcHubs, !hubs.isEmpty {
                        Menu("Choose a discovered hub") {
                            ForEach(hubs) { found in
                                Button(found.name) { hub = found.hubHash }
                            }
                        }
                    }
                    Button("Find rooms on this hub") {
                        let address = hub.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task { _ = await family.discoverRooms(address) }
                    }
                    .disabled(family.state?.tcpOnline != true || hub.trimmingCharacters(in: .whitespacesAndNewlines).count != 32)
                    if let listing {
                        Text(listing.status).font(.caption)
                        ForEach(listing.rooms) { found in
                            Button(found.hasPassword ? "#\(found.channel) · Password required" : "#\(found.channel)") {
                                channel = found.channel
                                if name.isEmpty { name = found.channel }
                            }
                        }
                    }
                    TextField("Channel name", text: $channel).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField(room?.hasPassword == true ? "New password (optional)" : "Room password (optional)", text: $password)
                    if room?.hasPassword == true { Toggle("Remove stored password", isOn: $clearPassword) }
                    Toggle("Read only", isOn: $readOnly)
                }
                Section {
                    Button("Save approved room") {
                        busy = true
                        Task {
                            if await family.saveRoom(id: room?.id, name: name, hub: hub, channel: channel,
                                                     readOnly: readOnly, password: password, clearPassword: clearPassword) {
                                dismiss()
                            }
                            busy = false
                        }
                    }
                    .disabled(busy || name.isEmpty || hub.isEmpty || channel.isEmpty || (clearPassword && !password.isEmpty))
                    if room != nil {
                        Button("Remove room approval", role: .destructive) { confirmRemoval = true }.disabled(busy)
                    }
                    if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                }
            }
        }
        .navigationTitle(room == nil ? "Approve room" : "Edit room")
        .sheet(isPresented: $showingScanner) {
            NavigationStack {
                FamilyQRScanner { payload in
                    showingScanner = false
                    busy = true
                    Task {
                        await importCard(payload)
                        busy = false
                    }
                } onError: {
                    showingScanner = false
                    family.error = "The camera couldn’t start. You can import a QR image instead."
                }
                .navigationTitle("Scan room QR code")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { showingScanner = false }
                    }
                }
            }
        }
        .onAppear {
            if let room {
                name = room.name
                hub = room.key
                channel = room.channel
                readOnly = room.readOnly
            }
        }
        .confirmationDialog("Remove this room approval?", isPresented: $confirmRemoval, titleVisibility: .visible) {
            Button("Remove room approval", role: .destructive) {
                guard let room else { return }
                busy = true
                Task {
                    if await family.removeRoom(room.id) { dismiss() }
                    busy = false
                }
            }
        }
    }

    private func importCard(_ text: String) async {
        guard let card = await family.readRoomCard(text) else { return }
        name = card.name.isEmpty ? card.channel : card.name
        hub = card.key
        channel = card.channel
        password = ""
    }
}
