import AVFoundation
import Combine
import CoreLocation
import CryptoKit
import BackgroundTasks
import Network
import OSLog
import SwiftUI
import UIKit

@main
@MainActor
struct FamilyLiveApp: App {
    @UIApplicationDelegateAdaptor(FamilyNotifications.self) private var notifications
    @StateObject private var family = FamilyModel.shared
    @ObservedObject private var systemCalls = FamilySystemCalls.shared
    @Environment(\.scenePhase) private var scenePhase

    private var keepScreenAwake: Bool {
        scenePhase == .active && family.state?.voice?.enabled == true && family.state?.voiceKeepAwake == true
    }

    var body: some Scene {
        WindowGroup {
            FamilyHome(family: family)
                .onChange(of: keepScreenAwake, initial: true) {
                    UIApplication.shared.isIdleTimerDisabled = keepScreenAwake
                }
                .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)
                    .receive(on: RunLoop.main)) { notification in
                    let rawReason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                    let reason = rawReason.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
                    if reason == .newDeviceAvailable || reason == .oldDeviceUnavailable {
                        family.reconnectVoiceAudio()
                        FamilySIP.shared.routeChanged()
                    }
                }
                .onReceive(NotificationCenter.default.publisher(for: .familyInboxData)
                    .receive(on: RunLoop.main)) { _ in family.receivedInboxData() }
                .onReceive(NotificationCenter.default.publisher(for: .familyRadioData)
                    .receive(on: RunLoop.main)) { _ in family.receivedRadioData() }
                .onChange(of: systemCalls.audioReady) { family.systemAudioChanged() }
                .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)
                    .receive(on: RunLoop.main)) { notification in
                    family.audioInterruption(notification)
                }
                .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.mediaServicesWereResetNotification)
                    .receive(on: RunLoop.main)) { _ in family.audioServicesReset() }
                .task(id: scenePhase) {
                    family.notifications = notifications
                    notifications.openMessage = { [weak family = family] contactID, messageID in
                        family?.openNotification(contactID: contactID, messageID: messageID)
                    }
                    if scenePhase == .active {
                        family.stopCallWakePolling()
                        family.stopRadioWake()
                        await family.setVoicePresence(true)
                        await family.refreshNotificationPermission()
                        family.checkMailboxOnNextRefresh()
                    } else if scenePhase == .background {
                        await family.setVoicePresence(false)
                        await family.suspendLocation()
                        await family.lock()
                        await family.scheduleMailboxRefresh()
                    }
                    while !Task.isCancelled && (scenePhase == .active || family.finishingSend || family.hasCallInProgress) {
                        await family.refresh()
                        if scenePhase == .active {
                            await family.checkMailboxIfDue()
                            family.sampleLocationIfDue()
                        }
                        do { try await Task.sleep(for: .seconds(1)) }
                        catch { break }
                    }
                }
        }
        .backgroundTask(.appRefresh(FamilyModel.mailboxRefreshID)) {
            await family.refreshMailboxInBackground(notifications: notifications)
        }
    }
}

@MainActor
final class FamilyModel: ObservableObject, FamilyCallWakeRuntime {
    static let shared = FamilyModel()
    private var callWakePolling: Task<Void, Never>?
    private var callWakeGeneration = 0

    func stopCallWakePolling() {
        callWakeGeneration += 1
        callWakePolling?.cancel(); callWakePolling = nil
    }

    /// Reuse this model's single embedded runtime. Poll only while CallKit owns
    /// the pending/active approved call; this is not an idle background service.
    func beginCallWake() async throws {
        await refresh()
        guard state?.setupComplete == true, state?.voice?.enabled == true else { throw URLError(.cannotConnectToHost) }
        guard UIApplication.shared.applicationState != .active, callWakePolling == nil,
              FamilySystemCalls.shared.hasCall else { return }
        callWakeGeneration += 1
        let generation = callWakeGeneration
        callWakePolling = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { if self.callWakeGeneration == generation { self.callWakePolling = nil } }
            while !Task.isCancelled, self.callWakeGeneration == generation, FamilySystemCalls.shared.hasCall {
                await self.refresh()
                do { try await Task.sleep(for: self.state?.voice?.call_state == "connected" ? .seconds(1) : .milliseconds(200)) }
                catch { return }
            }
            if !Task.isCancelled, self.callWakeGeneration == generation { await self.refresh() }
        }
    }
    @Published private(set) var state: FamilyReply?
    @Published private(set) var unlocked = false
    @Published var error = ""
    @Published private(set) var notificationsAllowed = false
    @Published var notificationContactID: Int?
    @Published private(set) var speakerOn = false
    #if DEBUG
    @Published private(set) var testNotificationDelivered = false
    @Published private(set) var testInboxSignalReceived = false

    var testTCPRecovered: Bool {
        guard ProcessInfo.processInfo.environment["FAMILY_TEST_RECONNECT"] == "1",
              let epoch = state?.tcpSession?.split(separator: ":").last else { return false }
        return (Int(epoch) ?? 0) > 1
    }
    #endif
    weak var notifications: FamilyNotifications?
    private var sendTask: UIBackgroundTaskIdentifier = .invalid
    private var sendsStarting = 0
    private var guardianEpoch = 0
    private var pendingNotification: (Int, String)?
    private var nextMailboxCheck = ContinuousClock.now
    private var nextRadioBatteryCheck = ContinuousClock.now
    static let mailboxRefreshID = "org.meshchat.family.ios.live.mailbox"
    private static let mailboxBackgroundCheckKey = "family.mailbox.lastBackgroundCheck"
    @Published private(set) var lastBackgroundMailboxCheck =
        UserDefaults.standard.object(forKey: FamilyModel.mailboxBackgroundCheckKey) as? Date
    private var schedulingMailboxRefresh = false
    var finishingSend: Bool { sendTask != .invalid }

    private let client = FamilyClient()
    private let voiceAudio = FamilyVoiceAudio()
    private let voiceLogger = Logger(subsystem: "org.meshchat.family", category: "Reticulum call")
    @Published private(set) var voiceError = ""
    private var failingAudioCallID: String?
    private var lastVoiceCallID: String?
    private var voiceInterrupted = false
    private var requestedVoiceSpeaker: Bool?
    private var presenceGeneration = 0
    var hasCallInProgress: Bool { state?.voice?.active == true || FamilySIP.shared.active }
    private lazy var radioWake = FamilyRadioWake(
        begin: { expiration in
            let identifier = UIApplication.shared.beginBackgroundTask(withName: "Receive Family radio messages") {
                Task { @MainActor in expiration() }
            }
            return identifier == .invalid ? nil : identifier.rawValue
        },
        end: { UIApplication.shared.endBackgroundTask(UIBackgroundTaskIdentifier(rawValue: $0)) },
        now: { ProcessInfo.processInfo.systemUptime },
        active: { UIApplication.shared.applicationState == .active },
        prepare: { [weak self] in await self?.refreshNotificationPermission() },
        refresh: { [weak self] in await self?.refresh() },
        pause: { try await Task.sleep(for: .seconds(1)) }
    )

    func receivedInboxData() {
        guard state?.setupComplete == true else { return }
        #if DEBUG
        if ProcessInfo.processInfo.environment["FAMILY_TEST_NOTIFICATIONS"] == "1" { testInboxSignalReceived = true }
        #endif
        radioWake.received()
    }

    func receivedRadioData() {
        guard state?.setupComplete == true,
              state?.rnode?.enabled == true || state?.meshcore?.enabled == true else { return }
        radioWake.received()
    }

    private var radioInbox: FamilyRadioInbox?

    func installRadioInbox(notifications: FamilyNotifications) {
        self.notifications = notifications
        if radioInbox == nil { radioInbox = FamilyRadioInbox(wake: radioWake) }
    }

    func restoredRadioLaunch() { radioInbox?.restored() }
    func stopRadioWake() { radioWake.stop() }

    private let locationSampler = FamilyLocationSampler()
    private let networkMonitor = NWPathMonitor()
    private var lastNetworkPath: NWPath?
    private var networkGeneration = 0
    private var sentNetworkGeneration = -1
    private var networkQualityContext: String {
        guard let path = lastNetworkPath else { return "ios:unknown" }
        let kind = path.usesInterfaceType(.wifi) ? "wifi" : path.usesInterfaceType(.cellular) ? "cellular" :
            path.usesInterfaceType(.wiredEthernet) ? "wired" : "other"
        let gateways = path.gateways.map { String(describing: $0) }.sorted().joined(separator: "|")
        let digest = SHA256.hash(data: Data(gateways.utf8)).prefix(6).map { String(format: "%02x", $0) }.joined()
        return "ios:\(kind):\(digest)"
    }

    private func syncNetworkQualityContext() async {
        guard state?.setupComplete == true, sentNetworkGeneration != networkGeneration else { return }
        let generation = networkGeneration
        do {
            _ = try await request("ios_network_context", ["context": networkQualityContext, "generation": generation])
            if generation == networkGeneration { sentNetworkGeneration = generation }
        } catch { /* A later foreground refresh retries this local metadata update. */ }
    }
    private var token = ""

    init() {
        networkMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in await self?.networkPathChanged(path) }
        }
        networkMonitor.start(queue: DispatchQueue(label: "family.network-path"))
    }

    private func networkPathChanged(_ path: NWPath) async {
        let previous = lastNetworkPath
        lastNetworkPath = path
        if previous != path { networkGeneration += 1 }
        await syncNetworkQualityContext()
        guard let previous, previous != path, lastNetworkPath == path, path.status == .satisfied, state?.setupComplete == true else { return }
        FamilySIP.shared.networkChanged()
        _ = try? await request("tcp_network_changed")
    }

    func refresh() async {
        do {
            await syncNetworkQualityContext()
            let updated = try await request("status")
            if let session = updated.tcpSession, session != state?.tcpSession {
                checkMailboxOnNextRefresh()
            }
            state = updated
            FamilyCallWakeOwner.shared.refreshPolicy()
            FamilySIP.shared.reconcile(updated)
            reconcileLocationSampling()
            if UIApplication.shared.applicationState == .active {
                notifications?.push.refresh(updated)
            }
            if FamilySIP.shared.active, let voice = updated.voice, voice.call_state == "incoming", let id = voice.call_id {
                _ = try? await request("voice_hangup", ["callId": id])
            } else { updateVoice(updated.voice) }
            resolveNotification()
            if notificationsAllowed {
                await notifications?.publish(updated.messages ?? [:])
                #if DEBUG
                if !testNotificationDelivered &&
                    ProcessInfo.processInfo.environment["FAMILY_TEST_NOTIFICATIONS"] == "1" {
                    testNotificationDelivered = await notifications?.hasDeliveredMessage(from: messages) ?? false
                }
                #endif
            }
            finishSendIfIdle()
            if UIApplication.shared.applicationState == .active {
                let now = ContinuousClock.now
                if updated.meshcore?.connected != true {
                    nextRadioBatteryCheck = now
                } else if now >= nextRadioBatteryCheck {
                    nextRadioBatteryCheck = now + .seconds(30)
                    _ = try? await request("radio_batteries")
                }
            }
        } catch { self.error = error.localizedDescription }
    }

    func setVoicePresence(_ active: Bool) async {
        presenceGeneration += 1
        var payload: [String: Any] = ["foreground": active, "generation": presenceGeneration]
        if !active, let voice = state?.voice, let key = voiceKey(voice),
           FamilySystemCalls.shared.contains(key) || (voice.call_state == "connected" && voiceAudio.callID == key.id) {
            payload["preserveCallId"] = key.id
        } else if !active {
            voiceAudio.stop()
            speakerOn = false
        }
        FamilySIP.shared.setForeground(active)
        _ = try? await request("voice_presence", payload)
    }

    func configureSystemCallControls(_ enabled: Bool) {
        guard !hasCallInProgress else { error = "End the current call before changing call controls."; return }
        if !FamilySystemCalls.shared.setEnabled(enabled) { error = FamilySystemCalls.shared.error }
    }

    private func voiceKey(_ voice: FamilyVoiceState?) -> FamilySystemCallKey? {
        guard let id = voice?.call_id, !id.isEmpty else { return nil }
        return FamilySystemCallKey(service: .reticulum, id: id)
    }

    func configureVoiceKeepAwake(_ enabled: Bool) async {
        _ = await perform("voice_keep_awake", ["token": token, "enabled": enabled])
    }

    func configureVoice(_ enabled: Bool) async {
        _ = await perform("voice_config", ["token": token, "enabled": enabled])
    }

    func rankedCallRoutes(contactID: Int) async -> [FamilyCallRoute] {
        let sip = FamilySIP.shared
        await syncNetworkQualityContext()
        let context = networkQualityContext
        do {
            let reply = try await request("call_routes", ["sip": [
                "enabled": sip.account?.enabled == true, "registered": sip.isRegistered, "quality_context": context
            ]])
            return (reply.callRoutes?[String(contactID)] ?? []).filter { ["sip", "reticulum"].contains($0.service) }
        } catch { self.error = error.localizedDescription; return [] }
    }

    func call(_ contact: FamilyContact, automatic: Bool = false) async {
        guard !FamilySIP.shared.active else { error = "End the SIP call first."; return }
        guard await microphoneAllowed(), !FamilySIP.shared.active else { return }
        voiceError = ""
        _ = await perform("voice_call", ["contactId": contact.id, "automatic": automatic])
    }

    func answerCall() async {
        guard let voice = state?.voice, voice.call_state == "incoming", let key = voiceKey(voice) else { return }
        if FamilySystemCalls.shared.owns(key) { await FamilySystemCalls.shared.requestAnswer(key) }
        else if await prepareVoiceAudio(key.id) { _ = await answerVoiceDirect(key.id) }
    }

    func endCall() async {
        guard let key = voiceKey(state?.voice) else { return }
        if FamilySystemCalls.shared.owns(key) { await FamilySystemCalls.shared.requestEnd(key) }
        else { await endVoiceDirect(key.id) }
    }

    func toggleVoiceMute() async {
        guard let voice = state?.voice, let key = voiceKey(voice) else { return }
        let muted = voice.muted != true
        if FamilySystemCalls.shared.owns(key) { await FamilySystemCalls.shared.requestMute(key, muted: muted) }
        else { _ = await muteVoiceDirect(key.id, muted: muted) }
    }

    private func prepareVoiceAudio(_ id: String) async -> Bool {
        guard await microphoneAllowed(), state?.voice?.call_id == id, !FamilySIP.shared.active else { return false }
        do { try FamilyCallAudioSession.configure(); return true }
        catch { self.error = error.localizedDescription; return false }
    }

    private func answerVoiceDirect(_ id: String) async -> Bool {
        guard state?.voice?.call_id == id, state?.voice?.call_state == "incoming", !FamilySIP.shared.active else { return false }
        return await perform("voice_answer", ["callId": id])
    }

    private func endVoiceDirect(_ id: String) async {
        if voiceAudio.callID == id { voiceAudio.stop(); speakerOn = false }
        _ = await perform("voice_hangup", ["callId": id])
    }

    private func muteVoiceDirect(_ id: String, muted: Bool) async -> Bool {
        guard state?.voice?.call_id == id, state?.voice?.active == true else { return false }
        return await perform("voice_mute", ["callId": id, "muted": muted])
    }

    var voiceCaptureStatus: String { voiceInterrupted ? "Audio paused by iOS" : voiceAudio.captureStatus }

    func systemAudioChanged() {
        if FamilySystemCalls.shared.audioReady { voiceInterrupted = false }
        reconcileVoiceAudio(state?.voice)
        FamilySIP.shared.systemAudioChanged()
    }

    func audioInterruption(_ notification: Notification) {
        guard let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        if type == .began {
            FamilySystemCalls.shared.systemAudioDeactivated()
            voiceInterrupted = true
            voiceAudio.stop()
            speakerOn = false
            FamilySIP.shared.interruptionBegan()
        } else {
            let rawOptions = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            let resume = AVAudioSession.InterruptionOptions(rawValue: rawOptions).contains(.shouldResume)
            Task {
                if resume { voiceInterrupted = false; reconcileVoiceAudio(state?.voice) }
                else if let key = voiceKey(state?.voice), !FamilySystemCalls.shared.owns(key) { await endVoiceDirect(key.id) }
                await FamilySIP.shared.interruptionEnded(shouldResume: resume)
            }
        }
    }

    func audioServicesReset() {
        voiceAudio.resetMediaServices()
        speakerOn = false
        FamilySystemCalls.shared.systemReset()
        if let key = voiceKey(state?.voice) { Task { await endVoiceDirect(key.id) } }
        FamilySIP.shared.mediaServicesReset()
        voiceError = "Audio services restarted. Please call again."
    }

    func reconnectVoiceAudio() {
        guard state?.voice?.call_state == "connected", !voiceInterrupted else { return }
        voiceAudio.stop()
        reconcileVoiceAudio(state?.voice)
    }

    func toggleSpeaker() {
        do {
            guard voiceAudio.callID != nil, !FamilyCallAudioSession.hasExternalOutput else { return }
            requestedVoiceSpeaker = !speakerOn
            try voiceAudio.setSpeaker(!speakerOn)
            speakerOn = voiceAudio.usingBuiltInSpeaker
        } catch { self.error = error.localizedDescription }
    }

    private func microphoneAllowed() async -> Bool {
        let allowed = await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
        if !allowed { error = "Allow microphone access in iOS Settings to make or answer calls." }
        return allowed
    }

    private func updateVoice(_ voice: FamilyVoiceState?) {
        if let id = voice?.call_id, !id.isEmpty, id != lastVoiceCallID {
            if let previous = lastVoiceCallID {
                FamilySystemCalls.shared.finish(FamilySystemCallKey(service: .reticulum, id: previous))
            }
            lastVoiceCallID = id
            voiceError = ""
            requestedVoiceSpeaker = nil
            voiceInterrupted = false
        }
        if let failure = voice?.error, !failure.isEmpty, failure != voiceError {
            voiceError = failure
            voiceLogger.error("Reticulum call failed: \(failure, privacy: .private)")
        }
        reconcileSystemCall(voice)
        reconcileVoiceAudio(voice)
    }

    private func reconcileSystemCall(_ voice: FamilyVoiceState?) {
        guard let voice, voice.active, let key = voiceKey(voice), voice.call_state != "ending" else {
            if let id = lastVoiceCallID { FamilySystemCalls.shared.finish(FamilySystemCallKey(service: .reticulum, id: id)) }
            return
        }
        guard FamilySystemCalls.shared.enabled else { return }
        guard let target = voice.target,
              let approved = state?.contacts?.first(where: { $0.addresses["lxst"]?.lowercased() == target.lowercased() }) else {
            Task { await endVoiceDirect(key.id) }
            return
        }
        let actions = FamilySystemCallActions(
            prepareAudio: { [weak self] in await self?.prepareVoiceAudio(key.id) ?? false },
            start: { [weak self] in self?.state?.voice?.call_id == key.id },
            answer: { [weak self] in await self?.answerVoiceDirect(key.id) ?? false },
            end: { [weak self] in await self?.endVoiceDirect(key.id) },
            mute: { [weak self] muted in await self?.muteVoiceDirect(key.id, muted: muted) ?? false }
        )
        let known = FamilySystemCalls.shared.contains(key)
        let pending = voice.call_state == "incoming" ? FamilyCallWakeOwner.shared.pendingIncoming(peer: target.lowercased()) : nil
        // An expired/cancelled wake must not become a second ordinary call
        // report while the app is backgrounded and its real link arrives late.
        if voice.call_state == "incoming", !known, pending == nil,
           UIApplication.shared.applicationState != .active {
            Task { await endVoiceDirect(key.id) }
            return
        }
        let accepted: Bool
        if !known, let pending {
            accepted = FamilySystemCalls.shared.attachIncoming(pending, to: key, actions: actions)
            if accepted { FamilyCallWakeOwner.shared.attached(pending, to: key) }
        } else {
            accepted = FamilySystemCalls.shared.track(key, name: approved.name, incoming: voice.call_state == "incoming", actions: actions)
        }
        if !accepted { Task { await endVoiceDirect(key.id) }; return }
        FamilySystemCalls.shared.update(key, connected: voice.call_state == "connected")
    }

    private func reconcileVoiceAudio(_ voice: FamilyVoiceState?) {
        guard let voice, voice.call_state == "connected", let key = voiceKey(voice),
              !voiceInterrupted, FamilySystemCalls.shared.allowsAudio(key),
              UIApplication.shared.applicationState == .active || FamilySystemCalls.shared.owns(key) || voiceAudio.callID == key.id else {
            if voiceAudio.callID != nil {
                voiceAudio.stop()
                speakerOn = false
            }
            return
        }
        let id = key.id
        guard failingAudioCallID != id else { return }
        do {
            if voiceAudio.callID == id {
                try voiceAudio.recoverStalledCapture()
            } else {
                try voiceAudio.start(callID: id, managedAudio: FamilySystemCalls.shared.owns(key))
                if let requestedVoiceSpeaker, !FamilyCallAudioSession.hasExternalOutput {
                    try voiceAudio.setSpeaker(requestedVoiceSpeaker)
                }
            }
            speakerOn = voiceAudio.usingBuiltInSpeaker
        } catch {
            failingAudioCallID = id
            voiceError = "Call audio could not start. \(error.localizedDescription)"
            voiceLogger.error("Native call audio failed: \(error.localizedDescription, privacy: .private)")
            Task { _ = try? await request("voice_hangup", ["callId": id]) }
        }
    }

    func openNotification(contactID: Int, messageID: String) {
        pendingNotification = (contactID, messageID)
        resolveNotification()
    }

    private func resolveNotification() {
        guard let (contactID, messageID) = pendingNotification,
              let contacts = state?.contacts, let messages = state?.messages else { return }
        pendingNotification = nil
        guard contacts.contains(where: { $0.id == contactID }),
              messages[String(contactID)]?.contains(where: { $0.id == messageID && $0.incoming }) == true else { return }
        notificationContactID = contactID
    }

    private var messages: [FamilyMessage] {
        state?.messages?.values.flatMap { $0 } ?? []
    }

    func refreshNotificationPermission() async {
        notificationsAllowed = await notifications?.isAuthorized() ?? false
    }

    func enableNotifications() async {
        do {
            notificationsAllowed = try await notifications?.authorize(existingMessages: messages) ?? false
            error = notificationsAllowed ? "" : "Allow neXt Family notifications in iOS Settings."
        } catch { self.error = error.localizedDescription }
    }

    func loadCallAlertRoute(contactID: Int) async throws -> FamilyCallAlertRoute? {
        try await request("call_alert_route_get", ["token": token, "contactId": contactID]).callAlertRoute
    }

    func saveCallAlertRoute(contactID: Int, route: FamilyCallAlertRoute?) async throws {
        let value: Any
        if let route { value = ["provider": route.provider, "audience": route.audience] }
        else { value = NSNull() }
        _ = try await request("call_alert_route_set", ["token": token, "contactId": contactID, "route": value])
    }

    func loadMailboxRoute(contactID: Int) async throws -> FamilyMailboxRoute? {
        try await request("mailbox_route_get", ["token": token, "contactId": contactID]).mailboxRoute
    }

    func saveMailboxRoute(contactID: Int, route: FamilyMailboxRoute?) async throws {
        let value: Any
        if let route {
            value = ["provider": route.provider, "audience": route.audience, "relay": route.relay]
        } else {
            value = NSNull()
        }
        _ = try await request("mailbox_route_set", ["token": token, "contactId": contactID, "route": value])
    }

    func saveMailbox(_ address: String) async -> Bool {
        let previousAddress = state?.mailbox?.address
        let saved = await perform("mailbox_config", [
            "token": token, "address": address.trimmingCharacters(in: .whitespacesAndNewlines)
        ])
        if saved {
            if previousAddress != state?.mailbox?.address {
                lastBackgroundMailboxCheck = nil
                UserDefaults.standard.removeObject(forKey: Self.mailboxBackgroundCheckKey)
            }
            nextMailboxCheck = .now
            await scheduleMailboxRefresh()
        }
        return saved
    }

    func checkMailboxOnNextRefresh() {
        nextMailboxCheck = .now
    }

    func checkMailboxIfDue() async {
        guard mailboxEnabled, state?.tcpOnline == true, ContinuousClock.now >= nextMailboxCheck else { return }
        nextMailboxCheck = .now + .seconds(60)
        _ = try? await request("mailbox_sync")
    }

    private var mailboxEnabled: Bool {
        !(state?.mailbox?.address.isEmpty ?? true)
    }

    func scheduleMailboxRefresh(retryIfStateUnknown: Bool = false) async {
        let scheduler = BGTaskScheduler.shared
        if state != nil && !mailboxEnabled {
            scheduler.cancel(taskRequestWithIdentifier: Self.mailboxRefreshID)
            return
        }
        // On a cold background launch the scene can arrive before the backend loads.
        // Only a loaded mailbox setting can prove that the pending request should be canceled.
        guard mailboxEnabled || retryIfStateUnknown, !schedulingMailboxRefresh else { return }
        schedulingMailboxRefresh = true
        defer { schedulingMailboxRefresh = false }

        let pending = await scheduler.pendingTaskRequests()
        guard !Task.isCancelled,
              mailboxEnabled || (retryIfStateUnknown && state == nil),
              !pending.contains(where: { $0.identifier == Self.mailboxRefreshID }) else { return }
        let request = BGAppRefreshTaskRequest(identifier: Self.mailboxRefreshID)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        do { try scheduler.submit(request) }
        catch { NSLog("Family mailbox background refresh unavailable: %@", error.localizedDescription) }
    }

    private func recordBackgroundMailboxCheck() {
        let date = Date()
        lastBackgroundMailboxCheck = date
        UserDefaults.standard.set(date, forKey: Self.mailboxBackgroundCheckKey)
    }

    func refreshMailboxInBackground(notifications: FamilyNotifications) async {
        self.notifications = notifications
        // Requeue first so an expired task or a failed cold start cannot stop future refreshes.
        await scheduleMailboxRefresh(retryIfStateUnknown: true)
        guard !Task.isCancelled, UIApplication.shared.applicationState != .active else { return }
        await lock()
        await refreshNotificationPermission()
        let deadline = ContinuousClock.now + .seconds(22)
        var requestedSession: String?
        var requestedAddress: String?
        while !Task.isCancelled && ContinuousClock.now < deadline &&
                UIApplication.shared.applicationState != .active {
            await refresh()
            if state != nil && !mailboxEnabled {
                await scheduleMailboxRefresh()
                return
            }
            guard !Task.isCancelled, UIApplication.shared.applicationState != .active else { return }
            if let session = state?.tcpSession, let mailbox = state?.mailbox {
                if requestedSession == session && requestedAddress == mailbox.address {
                    if mailbox.status == "complete" {
                        recordBackgroundMailboxCheck()
                        return
                    }
                    if mailbox.status == "failed" { return }
                } else if let status = try? await request("mailbox_sync").mailbox?.status,
                          status == "syncing" || status == "complete" {
                    // Accept completion only after the next snapshot confirms the same connection.
                    requestedSession = session
                    requestedAddress = mailbox.address
                }
            } else {
                requestedSession = nil
                requestedAddress = nil
            }
            do { try await Task.sleep(for: .seconds(1)) }
            catch { return }
        }

        // A sync can save a message during the last polling interval.
        guard !Task.isCancelled, UIApplication.shared.applicationState != .active else { return }
        await refresh()
        if let requestedSession, let requestedAddress,
           state?.tcpSession == requestedSession, state?.mailbox?.address == requestedAddress,
           state?.mailbox?.status == "complete" {
            recordBackgroundMailboxCheck()
        }
    }

    func send(contactID: Int, text: String, files: [FamilyDraftAttachment] = [], method: FamilyMessageMethod = .automatic) async -> Bool {
        sendsStarting += 1
        if !finishingSend {
            sendTask = UIApplication.shared.beginBackgroundTask(withName: "Finish Family message") { [weak self] in
                self?.endSendTask()
            }
        }
        defer {
            sendsStarting -= 1
            finishSendIfIdle()
        }
        var payload: [String: Any] = ["contactId": contactID, "text": text, "method": method.rawValue]
        if !files.isEmpty {
            payload["attachments"] = files.map { file -> [String: String] in
                var item = ["name": file.name, "data": file.data.base64EncodedString()]
                item["image"] = file.image
                return item
            }
        }
        return await perform("send", payload)
    }

    func attachmentURL(contactID: Int, messageID: String, index: Int) async throws -> URL {
        let reply = try await request("attachment_read", ["contactId": contactID, "messageId": messageID, "index": index])
        guard let path = reply.attachmentPath else { throw CocoaError(.fileNoSuchFile) }
        return URL(fileURLWithPath: path)
    }

    func setIncomingDeliveryLimit(_ bytes: Int) async -> Bool {
        await perform("incoming_delivery_limit", ["token": token, "bytes": bytes])
    }

    private func finishSendIfIdle() {
        let pending = messages.contains {
            !$0.incoming && ["Finding path", "Sending", "Sent · awaiting delivery proof"].contains($0.status)
        }
        if sendsStarting == 0 && !pending { endSendTask() }
    }

    private func endSendTask() {
        guard finishingSend else { return }
        let task = sendTask
        sendTask = .invalid
        UIApplication.shared.endBackgroundTask(task)
    }

    func perform(_ action: String, _ payload: [String: Any] = [:]) async -> Bool {
        do {
            let reply = try await request(action, payload)
            if reply.setupComplete != nil {
                state = reply
                FamilySIP.shared.reconcile(reply)
                reconcileLocationSampling()
                updateVoice(reply.voice)
            }
            self.error = ""
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func unlock(_ password: String) async {
        let epoch = guardianEpoch
        do {
            let reply = try await request("unlock", ["password": password])
            let newToken = reply.token ?? ""
            guard epoch == guardianEpoch else {
                _ = try? await request("lock", ["token": newToken])
                return
            }
            token = newToken
            unlocked = !token.isEmpty
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    func lock() async {
        guardianEpoch += 1
        guard !token.isEmpty else { return }
        let current = token
        token = ""
        unlocked = false
        _ = try? await request("lock", ["token": current])
    }

    func savePeer(id: String?, host: String, port: Int, enabled: Bool) async -> Bool {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test"), host == "rmap.world", enabled {
            guard await perform("device_name", ["token": token, "name": "Family iOS simulator test"]) else { return false }
        }
        #endif
        var payload: [String: Any] = ["token": token, "host": host, "port": port, "enabled": enabled]
        if let id { payload["id"] = id }
        return await perform("peer", payload)
    }

    func advertiseMeshCore(flood: Bool) async -> Bool {
        await perform("meshcore_advert", ["token": token, "flood": flood])
    }

    func saveMeshCore(_ config: [String: Any]) async -> Bool {
        await perform("meshcore_config", ["token": token, "config": config])
    }

    func saveRNode(_ config: [String: Any]) async -> Bool {
        await perform("rnode", ["token": token, "config": config])
    }

    func saveDeviceName(_ name: String) async -> Bool {
        await perform("device_name", ["token": token, "name": name])
    }

    func readRoomCard(_ text: String) async -> FamilyRoomCard? {
        let epoch = guardianEpoch
        do {
            let result = try await request("qr_parse", ["token": token, "text": text, "target": "room"])
            guard epoch == guardianEpoch, unlocked else { return nil }
            guard let card = result.roomCard, ["reticulum", "meshcore"].contains(card.service) else {
                error = "Choose a Reticulum or MeshCore room code."
                return nil
            }
            error = ""
            return card
        } catch {
            if epoch == guardianEpoch { self.error = error.localizedDescription }
            return nil
        }
    }

    func saveRoom(id: Int?, name: String, hub: String, channel: String,
                  readOnly: Bool, password: String, clearPassword: Bool, service: String = "reticulum") async -> Bool {
        var room: [String: Any] = ["name": name, "key": hub, "channel": channel,
                                    "service": service, "readOnly": readOnly]
        room["id"] = id
        return await perform("room_save", ["token": token, "room": room, "approved": true,
                                           "password": password, "clearPassword": clearPassword])
    }

    func saveRoomParticipantName(roomID: Int, participantID: String, name: String) async -> Bool {
        await perform("room_name", ["token": token, "roomId": roomID, "participantId": participantID, "name": name])
    }

    func discoverMeshCoreRooms() async -> Bool {
        await perform("room_discover", ["token": token, "service": "meshcore"])
    }

    func discoverRooms(_ hub: String) async -> Bool {
        await perform("room_discover", ["token": token, "hubHash": hub, "service": "reticulum"])
    }

    func removeRoom(_ id: Int) async -> Bool {
        await perform("room_remove", ["token": token, "roomId": id])
    }

    func selectMap(_ id: String) async -> Bool {
        await perform("map_select", ["token": token, "mapId": id])
    }

    func removeMap(_ id: String) async -> Bool {
        await perform("map_remove", ["token": token, "mapId": id])
    }

    func mapTile(id: String, x: Int, y: Int, z: Int) async throws -> Data? {
        try await request("map_tile", ["mapId": id, "x": x, "y": y, "z": z, "bestAvailable": true]).tile
    }

    func importMap(_ source: URL) async -> Bool {
        let epoch = guardianEpoch
        do {
            let permit = try await request("map_import_prepare", ["token": token])
            guard let path = permit.mapImportPath else { return false }
            let destination = URL(fileURLWithPath: path)
            defer { try? FileManager.default.removeItem(at: destination) }
            try await Task.detached(priority: .utility) {
                let scoped = source.startAccessingSecurityScopedResource()
                defer { if scoped { source.stopAccessingSecurityScopedResource() } }
                let attributes = try source.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard attributes.isRegularFile == true,
                      let size = attributes.fileSize, (1...2_147_483_648).contains(size) else {
                    throw CocoaError(.fileReadTooLarge)
                }
                try FileManager.default.copyItem(at: source, to: destination)
            }.value
            guard epoch == guardianEpoch, unlocked else { return false }
            return await perform("map_import", ["token": token, "path": path,
                                                "name": source.deletingPathExtension().lastPathComponent])
        } catch {
            if epoch == guardianEpoch { self.error = error.localizedDescription }
            return false
        }
    }

    func saveLocationPolicy(mapEnabled: Bool, userControls: Bool, contactIDs: Set<Int>) async -> Bool {
        await perform("location_policy", [
            "token": token, "mapEnabled": mapEnabled, "userControls": userControls,
            "contactIds": contactIDs.sorted()
        ])
    }

    func startLocation(_ duration: String) async -> Bool {
        guard await perform("location_start", ["token": token, "duration": duration]) else { return false }
        locationSampler.requestPermission()
        return true
    }

    func stopLocation() async {
        if await perform("location_stop", ["token": token]) { locationSampler.suspend() }
    }

    func configureBackgroundLocation(_ enabled: Bool) async -> Bool {
        await perform("ios_location_background", ["token": token, "enabled": enabled])
    }

    private func reconcileLocationSampling() {
        locationSampler.configure(state?.location, background: state?.locationBackgroundEnabled == true,
                                  foreground: UIApplication.shared.applicationState == .active) { [weak self] fix in
            guard let self, self.state?.location?.active == true,
                  UIApplication.shared.applicationState == .active ||
                    (self.state?.locationBackgroundEnabled == true && self.locationSampler.isContinuous) else { return }
            _ = try? await self.request("location_sample", ["fix": fix])
        }
    }

    func suspendLocation() async {
        reconcileLocationSampling()
        if state?.locationBackgroundEnabled == true && locationSampler.isContinuous { return }
        locationSampler.suspend()
        _ = try? await request("location_suspend")
    }

    func sampleLocationIfDue() {
        guard state?.location?.active == true else { return }
        reconcileLocationSampling()
        locationSampler.sampleIfDue { [weak self] fix in
            guard let self, UIApplication.shared.applicationState == .active,
                  self.state?.location?.active == true else { return }
            _ = try? await self.request("location_sample", ["fix": fix])
        }
    }

    func lookUpClient(_ address: String) async -> Bool {
        await perform("discover_client", ["token": token, "address": address])
    }

    func ownContactCard() async throws -> String? {
        let epoch = guardianEpoch
        let reply = try await request("contact_card", ["token": token])
        guard epoch == guardianEpoch, unlocked else { return nil }
        guard let text = reply.contactCardText else { return nil }
        guard let account = FamilySIP.shared.account, account.enabled,
              let address = FamilySIPAddress("sip:\(account.user)@\(account.host):\(account.port)") else { return text }
        guard var card = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { return text }
        var addresses = card["addresses"] as? [String: String] ?? [:]
        addresses["sip"] = address.uri
        card["addresses"] = addresses
        return String(data: try JSONSerialization.data(withJSONObject: card, options: [.sortedKeys]), encoding: .utf8)
    }

    func readContactCard(_ text: String) async -> FamilyContactCard? {
        let epoch = guardianEpoch
        do {
            let result = try await request("qr_parse", ["token": token, "text": text, "target": "contact"])
            guard epoch == guardianEpoch, unlocked else { return nil }
            guard let card = result.card,
                  card.addresses["lxmf"]?.isEmpty == false || card.addresses["lxst"]?.isEmpty == false || card.addresses["meshcore"]?.isEmpty == false || card.addresses["sip"]?.isEmpty == false else {
                error = "Choose a contact code with a messaging or calling address."
                return nil
            }
            error = ""
            return card
        } catch {
            if epoch == guardianEpoch { self.error = error.localizedDescription }
            return nil
        }
    }

    func resolveVoiceAddress(_ id: Int) async -> String? {
        do {
            return try await request("voice_resolve", ["token": token, "contactId": id]).address
        } catch {
            self.error = error.localizedDescription
            return nil
        }
    }

    func saveContact(
        id: Int? = nil,
        name: String,
        address: String,
        voiceAddress: String,
        identityPublicKey: String? = nil,
        meshcoreAddress: String? = nil,
        sipAddress: String? = nil,
        photo: String? = nil,
        replacePhoto: Bool = false
    ) async -> Bool {
        let current = state?.contacts ?? []
        let lxmf = address.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let lxst = voiceAddress.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let existingMesh = id.flatMap { id in current.first { $0.id == id } }?.addresses["meshcore"] ?? ""
        let mesh = (meshcoreAddress ?? existingMesh).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard mesh.isEmpty || mesh.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            error = "MeshCore public keys must contain 64 hexadecimal characters."
            return false
        }
        let previousSIP = id.flatMap { id in current.first { $0.id == id } }?.addresses["sip"] ?? ""
        let rawSIP = (sipAddress ?? previousSIP).trimmingCharacters(in: .whitespacesAndNewlines)
        let sip = FamilySIPAddress(rawSIP, defaultHost: FamilySIP.shared.account?.host ?? "premium.hamsoverip.com", defaultPort: FamilySIP.shared.account?.port ?? 5160)
        guard rawSIP.isEmpty || sip != nil else { error = "Enter a SIP extension or user@provider address."; return false }
        guard !lxmf.isEmpty || !lxst.isEmpty || !mesh.isEmpty || sip != nil else {
            error = "Enter at least one approved messaging or calling address."
            return false
        }
        guard [lxmf, lxst].allSatisfy({ $0.isEmpty || $0.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil }) else {
            error = "Reticulum addresses must contain 32 hexadecimal characters."
            return false
        }
        let previous = id.flatMap { id in current.first { $0.id == id } }
        if id != nil && previous == nil {
            error = "This contact is no longer approved."
            return false
        }
        var addresses = previous?.addresses ?? [:]
        let previousKey = addresses["lxmf"]?.lowercased() == lxmf ? previous?.identityPublicKey : nil
        addresses["lxmf"] = lxmf.isEmpty ? nil : lxmf
        addresses["lxst"] = lxst.isEmpty ? nil : lxst
        addresses["meshcore"] = mesh.isEmpty ? nil : mesh
        addresses["sip"] = sip?.uri
        let contact = FamilyContact(
            id: id ?? (current.map(\.id).max() ?? 0) + 1,
            name: name.trimmingCharacters(in: .whitespacesAndNewlines), addresses: addresses,
            identityPublicKey: identityPublicKey ?? previousKey,
            photo: replacePhoto ? photo : previous?.photo
        )
        var updated = current
        if let index = updated.firstIndex(where: { $0.id == contact.id }) { updated[index] = contact }
        else { updated.append(contact) }
        return await saveContacts(updated)
    }

    func removeContact(_ id: Int) async -> Bool {
        await saveContacts((state?.contacts ?? []).filter { $0.id != id })
    }

    private func saveContacts(_ contacts: [FamilyContact]) async -> Bool {
        let values = contacts.map(\.saveValue)
        return await perform("contacts", ["token": token, "contacts": values])
    }

    private func request(_ action: String, _ payload: [String: Any] = [:]) async throws -> FamilyReply {
        let data = try JSONSerialization.data(withJSONObject: ["action": action, "payload": payload])
        let result = try await client.request(String(decoding: data, as: UTF8.self))
        guard result.ok else {
            throw NSError(domain: "Family", code: 1, userInfo: [
                NSLocalizedDescriptionKey: result.error ?? "Family could not complete the request."
            ])
        }
        return result
    }
}

struct FamilyHome: View {
    @ObservedObject var family: FamilyModel
    @ObservedObject private var sip = FamilySIP.shared
    @State private var password = ""
    @State private var confirmation = ""
    @State private var showSetupPasswords = false
    @State private var enableInternetPeers = false
    @State private var showGuardian = false
    @State private var guardianDismissingForCall = false
    @State private var notificationContact: FamilyContact?
    @State private var showNotificationChat = false
    @AppStorage("next-family-appearance") private var appearance = ""
    @Environment(\.colorScheme) private var systemAppearance

    private var night: Bool { appearance.isEmpty ? systemAppearance == .dark : appearance == "night" }

    var body: some View {
        NavigationStack {
            Form {
                if family.state?.setupComplete == false {
                    Section("Guardian setup") {
                        Group {
                            if showSetupPasswords {
                                TextField("Guardian password", text: $password)
                                    .accessibilityIdentifier("setup-password")
                                TextField("Confirm guardian password", text: $confirmation)
                                    .accessibilityIdentifier("setup-confirmation")
                            } else {
                                SecureField("Guardian password", text: $password)
                                    .accessibilityIdentifier("setup-password")
                                SecureField("Confirm guardian password", text: $confirmation)
                                    .accessibilityIdentifier("setup-confirmation")
                            }
                        }
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        Button(showSetupPasswords ? "Hide passwords" : "Show passwords") {
                            showSetupPasswords.toggle()
                        }
                        .accessibilityIdentifier("setup-password-visibility")
                        Toggle("Enable Reticulum internet peers", isOn: $enableInternetPeers)
                            .accessibilityIdentifier("setup-internet-peers")
                        NavigationLink("Review device permissions") { FamilyPermissionCheckup() }
                        Button("Create guardian access") {
                            Task {
                                if await family.perform("setup", [
                                    "password": password, "confirmation": confirmation, "reticulumEnabled": enableInternetPeers
                                ]) {
                                    password = ""
                                    confirmation = ""
                                    showSetupPasswords = false
                                }
                            }
                        }
                    }
                } else if let state = family.state {
                    Section("Approved contacts") {
                        ForEach(state.contacts ?? []) { contact in
                            NavigationLink {
                                FamilyChat(family: family, contact: contact)
                            } label: {
                                HStack(spacing: 12) {
                                    FamilyContactAvatar(name: contact.name, photo: contact.photo)
                                    Text(contact.name)
                                }
                            }
                        }
                    }
                    if let rooms = state.rooms, !rooms.isEmpty {
                        Section("Approved rooms") {
                            ForEach(rooms) { room in
                                NavigationLink(room.name) { FamilyRoomChat(family: family, room: room) }
                            }
                        }
                    }
                    Section("Connection") {
                        Text(state.tcpOnline == true ? "Reticulum TCP connected" : "Reticulum TCP offline")
                        DisclosureGroup("TCP peers") {
                            ForEach(state.tcpConnections ?? []) { connection in
                                LabeledContent(connection.endpoint, value: connection.status)
                            }
                        }
                        if state.rnode?.enabled == true, let radio = state.rnodeRuntime {
                            Text(radio.online ? "RNode connected" : radio.connecting ? "Connecting to RNode" : "RNode offline")
                            if !radio.error.isEmpty {
                                Text(radio.error).font(.caption).foregroundStyle(.secondary)
                            }
                            if radio.online, let battery = radio.battery, let level = FamilyBatteryLevel.rnode(battery.percent) {
                                Label("RNode battery: \(Int(battery.percent))%", systemImage: battery.state == "charging" ? "battery.100.bolt" : "battery.\(level)")
                            }
                        }
                        if let radio = state.meshcore, radio.enabled { FamilyMeshCoreStatus(radio: radio) }
                        #if DEBUG
                        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test"), state.rrcIdentity != nil {
                            Text("Relay Chat ready").accessibilityIdentifier("relay-chat-ready")
                        }
                        #endif
                        if let mailbox = state.mailbox, !mailbox.address.isEmpty {
                            switch mailbox.status {
                            case "syncing": Text("Checking offline mailbox")
                            case "failed": Text("Couldn’t check offline mailbox")
                            case "complete": Text("Offline mailbox checked")
                            default: Text("Offline mailbox enabled")
                            }
                        }
                        if let address = state.address, !address.isEmpty {
                            Text(address).font(.caption.monospaced()).textSelection(.enabled)
                        }
                    }
                    if state.location?.mapEnabled == true {
                        Section {
                            NavigationLink("Family map") { FamilyLocationMap(family: family) }
                        }
                    }
                    if !family.notificationsAllowed {
                        Button("Enable message notifications") { Task { await family.enableNotifications() } }
                    }
                } else {
                    ProgressView("Starting Family")
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                if !family.voiceError.isEmpty { Text(family.voiceError).foregroundStyle(.red) }
            }
            .navigationTitle(family.state?.deviceName ?? "neXt Family")
            .preferredColorScheme(appearance.isEmpty ? nil : appearance == "night" ? .dark : .light)
            .toolbar {
                if family.state?.setupComplete == true {
                    ToolbarItem(placement: .topBarLeading) {
                        Button("Guardian settings", systemImage: "lock.shield") { showGuardian = true }
                            .labelStyle(.iconOnly)
                            .accessibilityIdentifier("guardian-settings")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(night ? "Day mode" : "Night mode", systemImage: night ? "sun.max" : "moon") {
                        appearance = night ? "day" : "night"
                    }
                    .accessibilityIdentifier("appearance-toggle")
                }
            }
            .navigationDestination(isPresented: $showNotificationChat) {
                if let contact = notificationContact {
                    FamilyChat(family: family, contact: contact).id(contact.id)
                }
            }
            .onChange(of: family.notificationContactID, initial: true) {
                guard let id = family.notificationContactID else { return }
                family.notificationContactID = nil
                guard let contact = family.state?.contacts?.first(where: { $0.id == id }) else { return }
                showGuardian = false
                notificationContact = contact
                showNotificationChat = true
            }
            .onChange(of: family.state?.voice?.active == true || sip.active) {
                if (family.state?.voice?.active == true || sip.active) && showGuardian {
                    guardianDismissingForCall = true
                    showGuardian = false
                }
            }
            .fullScreenCover(isPresented: Binding(
                get: { (family.state?.voice?.active == true || sip.active) && !showGuardian && !guardianDismissingForCall },
                set: { _ in }
            )) {
                Group {
                    if sip.active { FamilySIPCall() }
                    else { FamilyVoiceCall(family: family) }
                }.interactiveDismissDisabled()
            }
            .sheet(isPresented: $showGuardian, onDismiss: {
                guardianDismissingForCall = false
                Task { await family.lock() }
            }) {
                FamilyGuardian(family: family)
            }
        }
    }
}

struct FamilyGuardian: View {
    @ObservedObject var family: FamilyModel
    @Environment(\.dismiss) private var dismiss
    @State private var password = ""
    @State private var host = "rmap.world"
    @State private var port = "4343"
    @State private var peerEnabled = false
    @State private var peerID: String?
    @State private var savingPeer = false
    @FocusState private var editingDeviceName: Bool
    @State private var mailboxAddress = ""
    @State private var mailboxSaved = false
    @State private var deviceName = ""
    @State private var deviceNameSaved = false
    @State private var showPassword = false

    var body: some View {
        NavigationStack {
            Form {
                if family.unlocked {
                    NavigationLink("Permission checkup") { FamilyPermissionCheckup() }
                    Section("Approved contacts") {
                        NavigationLink("My contact QR") { FamilyOwnContactQR(family: family) }
                        NavigationLink("Add approved contact") { FamilyContactApproval(family: family) }
                        ForEach(family.state?.contacts ?? []) { contact in
                            NavigationLink(contact.name) { FamilyContactEditor(family: family, contact: contact) }
                        }
                    }
                    Section("Device name") {
                        TextField("Device name", text: $deviceName)
                            .accessibilityIdentifier("device-name")
                            .focused($editingDeviceName)
                        Button("Save device name") {
                            editingDeviceName = false
                            Task { deviceNameSaved = await family.saveDeviceName(deviceName) }
                        }
                        if deviceNameSaved { Text("Device name saved") }
                    }
                    Section("Reticulum TCP peers") {
                        if family.state?.tcpOnline == true {
                            Text("Reticulum TCP connected").accessibilityIdentifier("guardian-peer-connected")
                        }
                        ForEach(family.state?.tcpConnections ?? []) { connection in
                            Button {
                                editPeer(connection)
                            } label: {
                                LabeledContent(connection.endpoint, value: connection.status)
                            }
                            .accessibilityHint("Edit TCP peer")
                            .disabled(savingPeer)
                        }
                        Button("Add TCP peer") { editPeer(nil) }.disabled(savingPeer)
                        Text(peerID == nil ? "New TCP peer" : "Edit TCP peer").font(.headline)
                        TextField("Hostname", text: $host).textInputAutocapitalization(.never)
                            .autocorrectionDisabled().accessibilityIdentifier("peer-host")
                        TextField("Port", text: $port).keyboardType(.numberPad)
                            .accessibilityIdentifier("peer-port")
                        Button(peerEnabled ? "Disable Reticulum TCP peer" : "Enable Reticulum TCP peer") {
                            peerEnabled.toggle()
                        }
                        .accessibilityIdentifier("peer-enabled")
                        Button("Save peer") {
                            savingPeer = true
                            Task {
                                if await family.savePeer(id: peerID, host: host, port: Int(port) ?? 0, enabled: peerEnabled),
                                   let saved = family.state?.tcpConnections?.first(where: {
                                       $0.host == host.trimmingCharacters(in: .whitespacesAndNewlines) && $0.port == Int(port)
                                   }) {
                                    editPeer(saved)
                                }
                                savingPeer = false
                            }
                        }
                        .disabled(savingPeer || host.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    if family.state?.voiceSupported == true {
                        Section("Reticulum calling") {
                            Button(family.state?.voice?.enabled == true ? "Disable Reticulum calling" : "Enable Reticulum calling") {
                                Task { await family.configureVoice(family.state?.voice?.enabled != true) }
                            }
                            if family.state?.voice?.ready == true {
                                Text("Reticulum calling ready").accessibilityIdentifier("reticulum-voice-ready")
                                if family.state?.tcpOnline != true && family.state?.rnodeRuntime?.online != true {
                                    Text("Waiting for a Reticulum connection").font(.footnote)
                                }
                            }
                            Toggle("Keep screen awake for calls", isOn: Binding(
                                get: { family.state?.voiceKeepAwake == true },
                                set: { enabled in Task { await family.configureVoiceKeepAwake(enabled) } }
                            ))
                            .disabled(family.state?.voice?.enabled != true)
                            Text("This option prevents auto-lock. Calls already answered can continue when the screen locks or you switch apps. Receiving new Reticulum calls while suspended needs optional call alerts in a compatible push-enabled build.")
                                .font(.footnote).foregroundStyle(.secondary)
                            if let address = family.state?.voice?.address, !address.isEmpty {
                                Text(address).font(.caption.monospaced()).textSelection(.enabled)
                            }
                            let incoming = family.state?.voice?.lastIncoming ?? ""
                            LabeledContent("Last incoming attempt", value: incoming.isEmpty ? "No incoming link recorded" : incoming)
                            if let error = family.state?.voice?.error, !error.isEmpty { Text(error).foregroundStyle(.red) }
                        }
                    }
                    Section("iOS call controls") {
                        Toggle("Use iOS call screen", isOn: Binding(
                            get: { FamilySystemCalls.shared.enabled },
                            set: { family.configureSystemCallControls($0) }
                        )).disabled(family.hasCallInProgress)
                        Text("Answer, decline, end and mute approved calls using iOS controls. For new calls while suspended, review Incoming Reticulum call alerts below. Personal previews still need Family open for new calls.")
                            .font(.footnote).foregroundStyle(.secondary)
                        if !FamilySystemCalls.shared.error.isEmpty {
                            Text(FamilySystemCalls.shared.error).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    Section {
                        NavigationLink("Incoming Reticulum call alerts") { FamilyCallAlertsSettings(family: family) }
                            .accessibilityIdentifier("family-call-alert-settings")
                        NavigationLink("SIP calling") { FamilySIPSettings(family: family) }
                        NavigationLink("MeshCore companion") { FamilyMeshCoreSettings(family: family) }
                        NavigationLink("RNode") { FamilyRNodeSettings(family: family) }
                        NavigationLink("Location sharing") { FamilyLocationSettings(family: family) }
                        NavigationLink("Incoming message size") { FamilyIncomingLimitSettings(family: family) }
                        NavigationLink("Offline maps") { FamilyOfflineMapSettings(family: family) }
                        if family.state?.roomsEnabled != false {
                            NavigationLink("Approved rooms") { FamilyRoomSettings(family: family) }
                        }
                    }
                    if let push = family.notifications?.push {
                        FamilyPushSettings(family: family, push: push)
                    }
                    Section("Offline message mailbox") {
                        TextField("LXMF propagation node address", text: $mailboxAddress)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button("Save mailbox") { Task { mailboxSaved = await family.saveMailbox(mailboxAddress) } }
                        if mailboxSaved { Text("Mailbox setting saved") }
                        Text("Leave blank to disable. Senders must use this mailbox for offline delivery.")
                            .font(.caption)
                        if UIApplication.shared.backgroundRefreshStatus != .available {
                            Text("Background App Refresh is unavailable. Family checks the mailbox when you open the app.")
                                .foregroundStyle(.secondary)
                        } else if let lastCheck = family.lastBackgroundMailboxCheck {
                            Text("Last background check: \(lastCheck.formatted(date: .abbreviated, time: .shortened))")
                                .foregroundStyle(.secondary)
                        }
                    }
                } else {
                    Group {
                        if showPassword {
                            TextField("Guardian password", text: $password)
                                .accessibilityIdentifier("unlock-password")
                        } else {
                            SecureField("Guardian password", text: $password)
                                .accessibilityIdentifier("unlock-password")
                        }
                    }
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    Button(showPassword ? "Hide password" : "Show password") { showPassword.toggle() }
                    Button("Unlock") {
                        Task {
                            await family.unlock(password)
                            password = ""
                            showPassword = false
                        }
                    }
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
            .accessibilityIdentifier("guardian-settings-form")
            .navigationTitle("Guardian settings")
            .onChange(of: family.unlocked, initial: true) {
                if family.unlocked { loadSettings() }
            }
            .toolbar { Button("Done") { dismiss() } }
        }
    }
    private func editPeer(_ peer: FamilyTCPConnection?) {
        peerID = peer?.id
        host = peer?.host ?? ""
        port = peer.map { String($0.port) } ?? "4343"
        peerEnabled = peer?.enabled ?? true
    }

    private func loadSettings() {
        deviceName = family.state?.deviceName ?? "neXt Family"
        editPeer(family.state?.tcpConnections?.first)
        mailboxAddress = family.state?.mailbox?.address ?? ""
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--isolated-family-test") {
            host = ProcessInfo.processInfo.environment["FAMILY_TEST_HOST"] ?? host
            port = ProcessInfo.processInfo.environment["FAMILY_TEST_PORT"] ?? port
        }
        #endif
    }

}

struct FamilyClientDiscovery: View {
    @ObservedObject var family: FamilyModel
    var service = "lxmf"
    var editingContactID: Int? = nil
    let select: (FamilyDiscoveredClient) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var search = ""
    @State private var requestedAddress: String?
    @State private var requesting = false

    private var query: String { search.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var lookup: FamilyClientLookup? { family.state?.clientLookup }
    private var approvedAddresses: Set<String> {
        Set((family.state?.contacts ?? []).filter { $0.id != editingContactID }
            .compactMap { $0.addresses[service]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() })
    }
    private var matches: [FamilyDiscoveredClient] {
        (family.state?.announces ?? []).filter { client in
            FamilyContactDiscoveryPolicy.matches(client, service: service, query: query,
                                                 approvedAddresses: approvedAddresses)
        }
    }

    var body: some View {
        Form {
            Section {
                TextField(service == "meshcore" ? "Name or MeshCore key" : "Name or LXMF address", text: $search)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                if service == "lxmf", query.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil,
                   !approvedAddresses.contains(query.lowercased()), matches.isEmpty {
                    Button("Look up address") {
                        let address = query.lowercased()
                        requestedAddress = nil
                        requesting = true
                        Task {
                            if await family.lookUpClient(address) { requestedAddress = address }
                            requesting = false
                        }
                    }
                    .disabled(requesting || lookup?.pending == true || family.state?.tcpOnline != true)
                }
                if (requesting || requestedAddress == query.lowercased()),
                   let message = lookup?.message, !message.isEmpty {
                    Text(message).font(.caption)
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
            }
            Section("Discovered clients") {
                if matches.isEmpty { Text("No matching clients") }
                ForEach(matches) { client in
                    Button {
                        select(client)
                        dismiss()
                    } label: {
                        VStack(alignment: .leading) {
                            Text(client.name)
                            Text(client.address).font(.caption.monospaced()).foregroundStyle(.secondary)
                        }
                    }
                    .accessibilityIdentifier("discovered-client-\(client.address)")
                }
            }
        }
        .navigationTitle(service == "meshcore" ? "Find MeshCore contact" : "Find messaging client")
    }
}

struct FamilyChat: View {
    @ObservedObject var family: FamilyModel
    @ObservedObject private var sip = FamilySIP.shared
    let contact: FamilyContact
    @State private var draft = ""
    @State private var submitting = false
    @State private var attachments: [FamilyDraftAttachment] = []
    @State private var confirmLargeSend = false
    @State private var method: FamilyMessageMethod = .automatic
    @FocusState private var editingMessage: Bool

    private var currentContact: FamilyContact? {
        family.state?.contacts?.first { $0.id == contact.id }
    }

    private var messagePolicy: FamilyMessagePolicy {
        FamilyMessagePolicy(original: contact, current: currentContact,
                            routes: family.state?.messageRoutes?[String(contact.id)] ?? [],
                            text: draft, hasAttachments: !attachments.isEmpty)
    }

    private var canSend: Bool { messagePolicy.issue(for: method) == nil }

    private func send() {
        guard canSend else { family.error = messagePolicy.issue(for: method) ?? "Messaging is unavailable."; return }
        let selectedMethod = method
        let text = draft
        let photos = attachments.filter { $0.image != nil }
        let first = attachments.filter { $0.image == nil } + Array(photos.prefix(1))
        guard first.reduce(0, { $0 + $1.data.count }) <= FamilyDraftAttachment.limit else {
            family.error = "Send some attachments separately. Each Reticulum message allows up to 9.95 MB."
            return
        }
        let batches = [first] + photos.dropFirst().map { [$0] }
        submitting = true
        Task {
            defer { submitting = false }
            for (index, batch) in batches.enumerated() {
                let textToSend = index == 0 ? text : ""
                let policy = FamilyMessagePolicy(original: contact, current: currentContact,
                    routes: family.state?.messageRoutes?[String(contact.id)] ?? [],
                    text: textToSend, hasAttachments: !batch.isEmpty)
                if let issue = policy.issue(for: selectedMethod) { family.error = issue; return }
                guard await family.send(contactID: contact.id, text: textToSend, files: batch, method: selectedMethod) else { return }
                if index == 0, draft == text { draft = "" }
                let sent = Set(batch.map(\.id))
                attachments.removeAll { sent.contains($0.id) }
            }
        }
    }

    var body: some View {
        Form {
            if let approved = currentContact, approved.addresses["sip"]?.isEmpty == false {
                Section {
                    NavigationLink {
                        FamilyCallMenu(family: family, contactID: approved.id)
                    } label: { Label("Call \(approved.name)", systemImage: "phone.fill") }
                    .disabled(sip.active || family.state?.voice?.active == true)
                }
            }
            Section("Messages") {
                ForEach(family.state?.messages?[String(contact.id)] ?? []) { message in
                    VStack(alignment: .leading) {
                        if !message.text.isEmpty { Text(message.text) }
                        ForEach(Array(message.files.enumerated()), id: \.offset) { index, item in
                            FamilyReceivedAttachment(family: family, contactID: contact.id, messageID: message.id,
                                                     index: index, item: item)
                        }
                        if let error = message.attachmentError { Text(error).font(.caption) }
                        Text(message.status).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Section {
                Picker("Connection", selection: $method) {
                    Text("Automatic").tag(FamilyMessageMethod.automatic)
                    ForEach(messagePolicy.approved) { route in Text(route.name).tag(route) }
                    if method != .automatic && !messagePolicy.approved.contains(method) {
                        Text("\(method.name) · approval changed").tag(method)
                    }
                }
                .accessibilityIdentifier("message-method")
                .accessibilityValue(method.name)
                .disabled(submitting)
                TextField("Message", text: $draft)
                    .accessibilityIdentifier("message-draft")
                    .focused($editingMessage)
                    .submitLabel(.done)
                    .onSubmit { editingMessage = false; FamilyKeyboard.dismiss() }
                if method == .meshcore || (method == .automatic && messagePolicy.available == [.meshcore]) {
                    Text("\(draft.trimmingCharacters(in: .whitespacesAndNewlines).utf8.count) of 160 bytes")
                        .font(.caption).foregroundStyle(.secondary)
                }
                FamilyAttachmentComposer(attachments: $attachments)
                    .disabled(messagePolicy.approved.isEmpty || submitting)
                Button("Send") {
                    if attachments.reduce(0, { $0 + $1.data.count }) > 900_000 { confirmLargeSend = true }
                    else { send() }
                }
                .disabled(!canSend || submitting || (draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && attachments.isEmpty))
                .confirmationDialog("This attachment may exceed the recipient’s limit", isPresented: $confirmLargeSend) {
                    Button("Send anyway") { send() }
                }
                if let issue = messagePolicy.issue(for: method) {
                    Text(issue).font(.footnote).accessibilityIdentifier("message-method-status")
                }
                if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                #if DEBUG
                if family.testNotificationDelivered { Text("Message notification delivered") }
                if family.testInboxSignalReceived { Text("Native inbox signal received") }
                if family.testTCPRecovered { Text("Reticulum TCP reconnected") }
                #endif
            }
        }
        .accessibilityIdentifier("private-conversation-form")
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle(currentContact?.name ?? contact.name)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done typing") { editingMessage = false; FamilyKeyboard.dismiss() }
                    .accessibilityIdentifier("finish-message-entry")
            }
            if let currentContact, currentContact.addresses["lxst"]?.isEmpty == false,
               family.state?.voice?.ready == true {
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink {
                        FamilyCallMenu(family: family, contactID: currentContact.id)
                    } label: { Label("Call", systemImage: "phone.fill") }
                }
            }
        }
    }
}


private struct FamilyPushSettings: View {
    @ObservedObject var family: FamilyModel
    @ObservedObject var push: FamilyPushRegistration
    @State private var provider = ""
    @State private var code = ""

    var body: some View {
        Section("Mailbox push alerts") {
            Text(push.status).accessibilityIdentifier("mailbox-push-status")
            if push.configured {
                Button("Retry") { push.retry() }.disabled(push.busy)
                if !push.stopping {
                    Button("Turn off push alerts", role: .destructive) { push.disable() }
                }
            } else {
                TextField("HTTPS provider address", text: $provider)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("Provider enrollment code", text: $code)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("Enable push alerts") {
                    Task {
                        guard family.unlocked else { return }
                        await push.enable(provider: provider, secret: code, state: family.state) {
                            family.unlocked
                        }
                        if push.configured { code = "" }
                    }
                }
                .accessibilityIdentifier("mailbox-push-enable")
                .disabled(push.busy || provider.isEmpty || code.isEmpty)
            }
            Text("Your private provider receives the Apple device token and approved Reticulum public keys. Alerts show a generic message. Mailbox delivery still works when push is off.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}
