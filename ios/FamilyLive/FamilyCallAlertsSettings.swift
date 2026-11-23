// SPDX-License-Identifier: 0BSD
import SwiftUI

struct FamilyCallAlertsSettings: View {
    @ObservedObject var family: FamilyModel
    @ObservedObject private var owner = FamilyCallWakeOwner.shared
    @ObservedObject private var registration = FamilyCallWakeOwner.shared.registration
    @Environment(\.scenePhase) private var scenePhase
    @State private var callers: [FamilyCallWakePolicy.Caller] = []
    @State private var selected: Set<String> = []
    @State private var provider = ""
    @State private var audience = ""
    @State private var code = ""
    @State private var showCode = false
    @FocusState private var typing: Bool

    var body: some View {
        Form {
            if family.unlocked {
                Section("Incoming Reticulum call alerts") {
                    Text(registration.status).font(.headline)
                        .accessibilityIdentifier("family-call-alert-status")
                    Text("Optional. A compatible provider can alert this device to a call from a contact you select, even while iPadOS has suspended Family.")
                    if !owner.eligible {
                        Text("Apple call push is unavailable in this personal preview. Receiving calls while fully suspended needs a push-enabled signed build and a compatible provider. Calls while Family is running still work.")
                            .font(.footnote).foregroundStyle(.secondary)
                            .accessibilityIdentifier("family-call-alert-unavailable")
                    }
                    if !registration.configured {
                        TextField("HTTPS call-alert provider", text: $provider)
                            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($typing).accessibilityIdentifier("family-call-alert-provider")
                            .disabled(!owner.eligible)
                        TextField("Provider audience", text: $audience)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($typing).accessibilityIdentifier("family-call-alert-audience")
                            .disabled(!owner.eligible)
                        enrollmentCode
                        Button("Enable call alerts") {
                            doneTyping()
                            if owner.enable(provider: provider, audience: audience, code: code, selected: selected,
                                            guardianUnlocked: { family.unlocked }) { code = "" }
                        }.disabled(!canReview || provider.isEmpty || audience.isEmpty || code.isEmpty)
                            .accessibilityIdentifier("family-call-alert-enable")
                    } else {
                        Button("Turn off call alerts", role: .destructive) {
                            doneTyping(); code = ""
                            owner.disable(guardianUnlocked: { family.unlocked })
                        }.disabled(registration.stopping)
                            .accessibilityIdentifier("family-call-alert-disable")
                        Button("Retry provider setup or removal") {
                            owner.retry(guardianUnlocked: { family.unlocked })
                        }.disabled(registration.busy)
                        if registration.stopping {
                            Text("If the provider changed its enrollment code, paste the replacement to finish removal. This cannot turn alerts back on.")
                                .font(.footnote).foregroundStyle(.secondary)
                            enrollmentCode
                            Button("Retry removal with this code") {
                                doneTyping()
                                owner.retry(guardianUnlocked: { family.unlocked }, removalCode: code)
                                code = ""
                            }.disabled(registration.busy || code.isEmpty)
                        } else if registration.needsReview {
                            Button("Confirm selected callers and resume") {
                                doneTyping()
                                _ = owner.resume(selected: selected, guardianUnlocked: { family.unlocked })
                            }.disabled(!canReview)
                                .accessibilityIdentifier("family-call-alert-resume")
                        }
                    }
                    if !owner.error.isEmpty { Text(owner.error).foregroundStyle(.red) }
                }
                if let provider = registration.recipientProvider, let audience = registration.recipientAudience {
                    Section("Provider details for approved callers") {
                        LabeledContent("HTTPS provider", value: provider).textSelection(.enabled)
                        LabeledContent("Audience", value: audience).textSelection(.enabled)
                        ShareLink(item: "Reticulum call-alert provider: \(provider)\nAudience: \(audience)") {
                            Label("Share provider details", systemImage: "square.and.arrow.up")
                        }
                        Text("Give these public details to an approved caller for their contact route. This shares no password, enrollment code or Apple token.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section("Contacts allowed to call while suspended") {
                    Text("Choose individual guardian-approved Reticulum voice contacts. Adding a contact later does not grant call-alert access automatically.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if callers.isEmpty {
                        Text("Enable Reticulum calling and receive a verified contact code or message before selecting callers.")
                            .font(.footnote)
                    }
                    ForEach(callers, id: \.voiceAddress) { caller in
                        Toggle(caller.name, isOn: Binding(
                            get: { selected.contains(caller.voiceAddress) },
                            set: { enabled in
                                if enabled { selected.insert(caller.voiceAddress) }
                                else { selected.remove(caller.voiceAddress) }
                            }))
                            .disabled(!owner.eligible || registration.busy || registration.configured && !registration.needsReview)
                    }
                    Button("Refresh call permissions") { load(initial: false) }
                        .disabled(registration.busy)
                }
                Section("Privacy and availability") {
                    Text("The selected provider receives the Apple call token, this device’s public identity key and selected callers’ public voice addresses. It receives no private identity key, contact names, audio, messages, photos or locations. This consent is separate from mailbox message alerts.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("Allow microphone access and enable iOS call controls before setup. Changing approved callers or disabling calling pauses alerts for review. This handles Reticulum calls; SIP needs its own compatible provider wake service.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } else {
                Text("Unlock Guardian settings to review call alerts.")
                    .accessibilityIdentifier("family-call-alert-locked")
            }
        }
        .navigationTitle("Incoming call alerts")
        .accessibilityIdentifier("family-call-alert-form")
        .toolbar {
            if typing { Button("Done typing") { doneTyping() } }
        }
        .onAppear { load(initial: true) }
        .onChange(of: family.unlocked) {
            if !family.unlocked { code = ""; showCode = false; doneTyping() }
        }
        .onChange(of: scenePhase) {
            if scenePhase != .active { code = ""; showCode = false; doneTyping() }
        }
        .onDisappear { code = ""; showCode = false }
    }
    private var enrollmentCode: some View {
        HStack {
            Group {
                if showCode { TextField("Enrollment code", text: $code) }
                else { SecureField("Enrollment code", text: $code) }
            }.textInputAutocapitalization(.never).autocorrectionDisabled().focused($typing)
                .privacySensitive().accessibilityIdentifier("family-call-alert-code")
            Button { showCode.toggle() } label: {
                Image(systemName: showCode ? "eye.slash" : "eye")
                    .accessibilityLabel(showCode ? "Hide code" : "Show code")
            }.buttonStyle(.borderless)
        }.disabled(!owner.eligible && !registration.stopping)
    }
    private var canReview: Bool {
        family.unlocked && owner.eligible && owner.permissionsReady && FamilySystemCalls.shared.enabled &&
            family.state?.voice?.enabled == true && !registration.busy && !selected.isEmpty
    }
    private func doneTyping() { typing = false; FamilyKeyboard.dismiss() }
    private func load(initial: Bool) {
        guard family.unlocked else { return }
        owner.refreshPolicy(); callers = owner.availableCallers()
        if initial { selected = Set(registration.selectedCallers.map(\.voiceAddress)) }
        selected.formIntersection(Set(callers.map(\.voiceAddress)))
    }
}
