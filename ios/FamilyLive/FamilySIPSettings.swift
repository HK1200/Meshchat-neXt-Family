import SwiftUI
import UIKit

struct FamilySIPSettings: View {
    @ObservedObject var family: FamilyModel
    @ObservedObject private var sip = FamilySIP.shared
    @State private var enabled = false
    @State private var user = ""
    @State private var host = "premium.hamsoverip.com"
    @State private var port = "5160"
    @State private var password = ""

    var body: some View {
        Form {
            if family.unlocked {
                Toggle("Enable SIP calling", isOn: $enabled)
                TextField("Account or extension", text: $user).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("Provider hostname", text: $host).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("Port", text: $port).keyboardType(.numberPad)
                SecureField("SIP password", text: $password)
                Button("Save SIP account") {
                    _ = sip.save(FamilySIPAccount(enabled: enabled, user: user.trimmingCharacters(in: .whitespacesAndNewlines),
                        host: host.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), port: Int(port) ?? 0, password: password))
                }
                NavigationLink("SIP open-source licenses") {
                    ScrollView {
                        Text((Bundle.main.url(forResource: "SIP-NOTICES", withExtension: "txt")
                            .flatMap { try? String(contentsOf: $0, encoding: .utf8) }) ?? "License file unavailable")
                            .font(.footnote).textSelection(.enabled).padding()
                    }.navigationTitle("SIP licenses")
                }
                Text(sip.status)
                if !sip.error.isEmpty { Text(sip.error).foregroundStyle(.red) }
                Text("Add a SIP address to each approved contact to allow calls. Incoming SIP calls currently require Family to stay open.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("SIP calling")
        .onAppear {
            if let account = sip.account {
                enabled = account.enabled
                user = account.user
                host = account.host
                port = String(account.port)
                password = account.password
            }
        }
    }
}

struct FamilySIPCall: View {
    @ObservedObject private var sip = FamilySIP.shared
    var body: some View {
        VStack(spacing: 24) {
            Text(sip.caller).font(.largeTitle)
            Text(sip.phase == "incoming" ? "Incoming SIP call" : sip.phase.capitalized)
            if sip.phase == "incoming" {
                Button("Answer", systemImage: "phone.fill") { Task { await sip.answer() } }.buttonStyle(.borderedProminent)
            }
            if sip.phase == "connected" {
                Button(sip.muted ? "Unmute" : "Mute", systemImage: "mic.slash") { sip.toggleMute() }
                if UIDevice.current.userInterfaceIdiom != .pad {
                    Button(sip.speaker ? "Turn speaker off" : "Use speaker", systemImage: "speaker.wave.2") { sip.toggleSpeaker() }
                }
            }
            Button(sip.phase == "incoming" ? "Decline" : "End call", systemImage: "phone.down.fill", role: .destructive) { sip.end() }
                .buttonStyle(.borderedProminent)
            if !sip.error.isEmpty { Text(sip.error).foregroundStyle(.red) }
        }.padding()
    }
}
