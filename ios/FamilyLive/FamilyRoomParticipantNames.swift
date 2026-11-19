import SwiftUI

struct FamilyRoomParticipantNames: View {
    @ObservedObject var family: FamilyModel
    let room: FamilyRoom
    @State private var names: [String: String] = [:]
    @State private var saving = false
    @State private var saved: Set<String> = []

    private var participants: [FamilyRoomMessage] {
        var seen: Set<String> = []
        return (family.state?.roomRuntime?[String(room.id)]?.messages ?? []).reversed().filter {
            guard let id = $0.participantId, !id.isEmpty else { return false }
            return seen.insert(id).inserted
        }.sorted { ($0.reportedName ?? "") < ($1.reportedName ?? "") }
    }

    var body: some View {
        Form {
            if family.unlocked, family.state?.roomsEnabled != false {
                Section {
                    Text("These names apply only inside this room. They do not approve anyone for private messages, calls, or location sharing.")
                }
                if participants.isEmpty {
                    ContentUnavailableView("No participants yet", systemImage: "person.2", description: Text("Names appear here after room messages arrive."))
                }
                ForEach(participants) { participant in
                    if let id = participant.participantId {
                        Section(participant.reportedName ?? id) {
                            Text(id).font(.caption).textSelection(.enabled)
                            TextField("Room-only name", text: Binding(
                                get: { names[id] ?? participant.savedName ?? "" },
                                set: { names[id] = $0; saved.remove(id) }
                            ))
                            Button(saved.contains(id) ? "Name saved" : "Save name") {
                                saving = true
                                Task {
                                    if await family.saveRoomParticipantName(roomID: room.id, participantID: id,
                                                                           name: names[id] ?? participant.savedName ?? "") {
                                        saved.insert(id)
                                    }
                                    saving = false
                                }
                            }.disabled(saving)
                            Text("Leave the name blank to restore the reported name. Up to 48 characters.")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
        }
        .navigationTitle("Participant names")
    }
}
