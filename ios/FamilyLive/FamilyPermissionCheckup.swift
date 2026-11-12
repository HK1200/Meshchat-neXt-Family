import AVFoundation
import CoreLocation
import SwiftUI
import UIKit
import UserNotifications

@MainActor
private final class PermissionLocation: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published private(set) var status: CLAuthorizationStatus = .notDetermined

    override init() {
        super.init()
        status = manager.authorizationStatus
        manager.delegate = self
    }

    func request() { manager.requestWhenInUseAuthorization() }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        status = manager.authorizationStatus
    }
}

@MainActor
struct FamilyPermissionCheckup: View {
    private enum Step: CaseIterable {
        case notifications, microphone, camera, location

        var title: String {
            switch self {
            case .notifications: "Notifications"
            case .microphone: "Microphone"
            case .camera: "Camera"
            case .location: "Location while using Family"
            }
        }

        var reason: String {
            switch self {
            case .notifications: "Show alerts when Family retrieves new messages."
            case .microphone: "Let the other person hear you during a Reticulum call."
            case .camera: "Scan contact and room QR codes."
            case .location: "Share your location with approved contacts while Family is open, when a guardian enables sharing."
            }
        }
    }

    private enum Access: Equatable { case ask, enabled, settings, locationServicesOff, locationRestricted }
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL
    @StateObject private var location = PermissionLocation()
    @State private var index = 0
    @State private var notificationStatus: UNAuthorizationStatus = .notDetermined
    @State private var locationServicesEnabled: Bool?
    @State private var requesting = false
    private let steps = Step.allCases

    var body: some View {
        Form {
            if index < steps.count {
                let step = steps[index]
                Section {
                    Text(step.reason)
                    switch access(step) {
                    case .enabled:
                        Text("Enabled").foregroundStyle(.secondary)
                    case .ask:
                        Button("Allow \(step.title.lowercased())") { request(step) }
                            .disabled(requesting)
                    case .locationServicesOff:
                        Text("On this device, open Settings → Privacy & Security → Location Services and turn on Location Services. Then return to Family.")
                    case .locationRestricted:
                        Text("Location access is restricted on this device. A guardian can check Screen Time or device management settings.")
                    case .settings:
                        if step == .location {
                            Text("In Family’s settings, tap Location and choose While Using the App. If Location is missing, check Settings → Privacy & Security → Location Services.")
                        }
                        Button("Open Family settings") {
                            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                        }
                    }
                    Button(access(step) == .enabled ? "Next" : "Skip") { index += 1 }
                        .disabled(requesting)
                } header: {
                    Text("\(index + 1) of \(steps.count) · \(step.title)")
                }
            } else {
                Section("Permission checkup complete") {
                    ForEach(steps, id: \.self) { step in
                        LabeledContent(step.title, value: access(step) == .enabled ? "Enabled" : "Not enabled")
                    }
                    Text("You can review these permissions again in Guardian settings.")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("Permission checkup")
        .task(id: scenePhase) {
            if scenePhase == .active {
                notificationStatus = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
                let servicesEnabled = await Task.detached(priority: .userInitiated) {
                    CLLocationManager.locationServicesEnabled()
                }.value
                guard !Task.isCancelled else { return }
                locationServicesEnabled = servicesEnabled
            }
        }
    }

    private func access(_ step: Step) -> Access {
        switch step {
        case .notifications:
            switch notificationStatus {
            case .authorized, .provisional, .ephemeral: return .enabled
            case .notDetermined: return .ask
            default: return .settings
            }
        case .microphone:
            switch AVAudioApplication.shared.recordPermission {
            case .granted: return .enabled
            case .undetermined: return .ask
            default: return .settings
            }
        case .camera:
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: return .enabled
            case .notDetermined: return .ask
            default: return .settings
            }
        case .location:
            if locationServicesEnabled == false { return .locationServicesOff }
            switch location.status {
            case .authorizedAlways, .authorizedWhenInUse: return .enabled
            case .notDetermined: return .ask
            case .restricted: return .locationRestricted
            case .denied: return .settings
            @unknown default: return .locationRestricted
            }
        }
    }

    private func request(_ step: Step) {
        if step == .location {
            location.request()
            return
        }
        requesting = true
        Task {
            switch step {
            case .notifications:
                _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
                notificationStatus = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
            case .microphone:
                let _: Bool = await withCheckedContinuation { continuation in
                    AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
                }
            case .camera:
                _ = await AVCaptureDevice.requestAccess(for: .video)
            case .location:
                break
            }
            requesting = false
        }
    }
}
