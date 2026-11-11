import SwiftUI
import UIKit

struct FamilyVoiceCall: View {
    @ObservedObject var family: FamilyModel

    var body: some View {
        if let voice = family.state?.voice {
            VStack(spacing: 24) {
                Image(systemName: "phone.circle.fill").font(.system(size: 68)).accessibilityHidden(true)
                Text(voice.caller_name ?? "Reticulum call").font(.largeTitle)
                Text(status(voice.call_state))
                if let profile = voice.profile, !profile.isEmpty { Text(profile).font(.caption) }
                if voice.call_state == "incoming" {
                    Button("Answer", systemImage: "phone.fill") { Task { await family.answerCall() } }
                        .buttonStyle(.borderedProminent)
                }
                if voice.call_state == "connected" {
                    HStack {
                        if UIDevice.current.userInterfaceIdiom != .pad {
                            Button(family.speakerOn ? "Turn speaker off" : "Use speaker", systemImage: "speaker.wave.2") {
                                family.toggleSpeaker()
                            }
                        }
                        Button(voice.muted == true ? "Unmute" : "Mute", systemImage: "mic.slash") {
                            Task { _ = await family.perform("voice_mute", ["muted": voice.muted != true]) }
                        }
                    }
                    .buttonStyle(.bordered)
                }
                Button(voice.call_state == "incoming" ? "Decline" : "End call", systemImage: "phone.down.fill", role: .destructive) {
                    Task { await family.endCall() }
                }
                .buttonStyle(.borderedProminent)
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                if !family.voiceError.isEmpty { Text(family.voiceError).foregroundStyle(.red) }
            }
            .padding()
        }
    }

    private func status(_ phase: String) -> String {
        switch phase {
        case "incoming": "Incoming Reticulum call"
        case "finding": "Finding Reticulum path"
        case "calling": "Calling"
        case "connected": "Connected"
        case "ending": "Ending call"
        default: "Call ended"
        }
    }
}
