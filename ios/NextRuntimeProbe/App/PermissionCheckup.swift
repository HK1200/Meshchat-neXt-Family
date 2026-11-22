import SwiftUI
import AVFoundation
import CoreBluetooth
import UserNotifications
import CoreLocation

@MainActor
private final class NextOptionalPermissions: NSObject, ObservableObject, CBCentralManagerDelegate, @preconcurrency CLLocationManagerDelegate {
    @Published private(set) var bluetooth = CBManager.authorization
    @Published private(set) var microphone = AVAudioApplication.shared.recordPermission
    @Published private(set) var camera = AVCaptureDevice.authorizationStatus(for: .video)
    @Published private(set) var location = CLAuthorizationStatus.notDetermined
    private lazy var locationManager: CLLocationManager = {
        let manager = CLLocationManager(); manager.delegate = self; return manager
    }()
    private var manager: CBCentralManager?
    func refresh() {
        microphone = AVAudioApplication.shared.recordPermission
        bluetooth = CBManager.authorization
        camera = AVCaptureDevice.authorizationStatus(for: .video)
        location = locationManager.authorizationStatus
    }
    func requestBluetooth() {
        guard bluetooth == .notDetermined, manager == nil else { return }
        // Authorization only: this manager never scans, advertises or connects.
        manager = CBCentralManager(delegate: self, queue: .main,
            options: [CBCentralManagerOptionShowPowerAlertKey: false])
    }
    func requestMicrophone() async {
        guard microphone == .undetermined else { return }
        _ = await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
        refresh()
    }
    func requestCamera() async {
        guard camera == .notDetermined else { return }
        _ = await AVCaptureDevice.requestAccess(for: .video)
        refresh()
    }
    func requestMapLocation() {
        guard locationManager.authorizationStatus == .notDetermined else { return }
        locationManager.requestWhenInUseAuthorization()
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) { location = manager.authorizationStatus }
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor [weak self] in self?.refresh() }
    }
}

struct NextPermissionCheckup: View {
    @ObservedObject var alerts: NextMessageAlerts
    let existing: () async throws -> [NextUnreadNotice]
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var optional = NextOptionalPermissions()
    @State private var step = 0
    @State private var busy = false
    @State private var error = ""
    private let titles = ["Message notifications", "Bluetooth radios", "Microphone for calls", "Camera", "Files and photos", "Local network", "Map location", "Screen locked and background delivery"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Step \(step + 1) of \(titles.count)").font(.subheadline).foregroundStyle(.secondary)
                        .accessibilityIdentifier("next-permission-step")
                    Text(titles[step]).font(.title2.bold())
                        .accessibilityIdentifier("next-permission-title")
                    content
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                    Text("You can skip optional access and return to this checkup later.")
                        .font(.footnote).foregroundStyle(.secondary)
                    HStack {
                        if step > 0 { Button("Back") { move(-1) } }
                        Spacer()
                        if step < titles.count - 1 { Button("Next") { move(1) }.buttonStyle(.borderedProminent) }
                        else { Button("Finish checkup") { dismiss() }.buttonStyle(.borderedProminent) }
                    }.padding(.top)
                }.padding()
            }
            .navigationTitle("Permission checkup")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task(id: scenePhase) {
                if scenePhase == .active { optional.refresh(); await alerts.refreshAuthorization() }
            }
        }
    }
    @ViewBuilder private var content: some View {
        switch step {
        case 0:
            Text("Allow a sound and private notification for unread messages. Notifications say a message arrived; they do not include the sender or message text.")
            LabeledContent("Notifications", value: alerts.enabled ? "Enabled" : "Not enabled")
            LabeledContent("Lock screen", value: alerts.lockScreenSetting == .enabled ? "Enabled" : "Check in device settings")
            if alerts.authorization == .notDetermined {
                Button("Allow message notifications") {
                    busy = true
                    Task {
                        defer { busy = false }
                        do { let baseline = try await existing(); try await alerts.authorize(existing: baseline) }
                        catch { self.error = "Notifications could not be prepared. Check the connection and try again." }
                    }
                }.disabled(busy).buttonStyle(.bordered)
            } else { settingsButton }
            Text("In iOS notification settings, enable Lock Screen, Sounds and the alert style you prefer. Focus and Silent Mode can still silence alerts.").font(.footnote)
        case 1:
            Text("Bluetooth is needed only if you choose an RNode or MeshCore companion. Allowing access here does not scan for radios, change pairing or connect a companion.")
            LabeledContent("Bluetooth", value: optional.bluetooth == .allowedAlways ? "Allowed" : "Not allowed yet")
            if optional.bluetooth == .notDetermined {
                Button("Allow Bluetooth radios") { optional.requestBluetooth() }.buttonStyle(.bordered)
            } else if optional.bluetooth != .allowedAlways { settingsButton }
        case 2:
            Text("Microphone access lets the other person hear you during a call. It is requested only when you allow it here or place or answer a call; reviewing this guide does not start recording.")
            LabeledContent("Microphone", value: optional.microphone == .granted ? "Allowed" : "Not allowed yet")
            if optional.microphone == .undetermined {
                Button("Allow microphone for calls") {
                    busy = true
                    Task { defer { busy = false }; await optional.requestMicrophone() }
                }.disabled(busy).buttonStyle(.bordered)
            } else if optional.microphone != .granted { settingsButton }
        case 3:
            Text("Camera access lets you take a photo to attach when you choose the camera. neXt does not turn the camera on in the background.")
            LabeledContent("Camera", value: optional.camera == .authorized ? "Allowed" : "Not allowed yet")
            if optional.camera == .notDetermined {
                Button("Allow camera") {
                    busy = true
                    Task { defer { busy = false }; await optional.requestCamera() }
                }.disabled(busy).buttonStyle(.bordered)
            } else if optional.camera != .authorized { settingsButton }
        case 4:
            Text("Choose the individual files or photos you want to attach using the system picker. You do not need to grant access to your entire photo library to choose an attachment.")
            Text("When saving a received file or photo, choose its destination in the system share sheet. No permission is requested just by reading this guide.").foregroundStyle(.secondary)
        case 5:
            Text("iOS may ask for Local Network access when you connect to a Reticulum peer, radio or SIP provider on your home network. Public internet services do not require that permission.")
            Text("Make the local connection from TCP connections, RNode or SIP accounts first, then tap Allow when iOS asks. If local access was blocked, enable Local Network for neXt in device settings. The switch may be absent until the first local connection attempt.").foregroundStyle(.secondary)
            settingsButton
        case 6:
            Text("Location is optional. Allow it when you want to center the map on your position or share a location with a contact. Reviewing this guide does not request a position or send your location.")
            LabeledContent("Location", value: optional.location == .authorizedWhenInUse || optional.location == .authorizedAlways ? "Allowed" : "Not allowed yet")
            if optional.location == .notDetermined {
                Button("Allow location for maps") { optional.requestMapLocation() }.buttonStyle(.bordered)
            } else if optional.location != .authorizedWhenInUse && optional.location != .authorizedAlways { settingsButton }
        default:
            Text("iOS can suspend neXt after you leave it or lock the screen. A connected Bluetooth radio can wake it briefly when iOS permits. There is no always-running iOS service.")
            Text("Internet-only message alerts while fully suspended, and incoming calls in that state, are not available in this preview. Notification permission cannot remove that iOS limit.").foregroundStyle(.secondary)
        }
    }
    private var settingsButton: some View {
        Button("Open neXt settings") {
            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        }.buttonStyle(.bordered)
    }
    private func move(_ delta: Int) {
        step = min(max(step + delta, 0), titles.count - 1)
        error = ""
    }
}
