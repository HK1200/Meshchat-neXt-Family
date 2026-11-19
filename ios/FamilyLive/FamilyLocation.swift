import CoreLocation
import MapKit
import SwiftUI
import UIKit

@MainActor
final class FamilyLocationSampler: NSObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var nextSample = ContinuousClock.now
    private var pending: (([String: Double]) async -> Void)?
    private var submit: (([String: Double]) async -> Void)?
    private var policy: FamilyLocationState?
    private var backgroundEnabled = false
    private var foreground = false
    private var expiryTask: Task<Void, Never>?
    private var scheduledUntil: TimeInterval?
    private var backgroundSupported: Bool {
        (Bundle.main.object(forInfoDictionaryKey: "UIBackgroundModes") as? [String])?.contains("location") == true
    }
    private lazy var session = FamilyLocationSession(start: { [weak self] in
        guard let self else { return }
        self.manager.allowsBackgroundLocationUpdates = true
        self.manager.showsBackgroundLocationIndicator = true
        self.manager.pausesLocationUpdatesAutomatically = false
        self.manager.startUpdatingLocation()
    }, stop: { [weak self] in
        guard let self else { return }
        self.manager.stopUpdatingLocation()
        self.manager.allowsBackgroundLocationUpdates = false
        self.manager.showsBackgroundLocationIndicator = false
    })

    var isContinuous: Bool { session.mode == .continuous }

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
    }

    func requestPermission() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
    }

    func configure(_ policy: FamilyLocationState?, background: Bool, foreground: Bool,
                   submit: @escaping ([String: Double]) async -> Void) {
        self.policy = policy; backgroundEnabled = background; self.foreground = foreground; self.submit = submit
        reconcile()
    }

    private func reconcile() {
        let previous = session.mode
        let allowed = manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways
        session.update(active: policy?.active == true, authorized: allowed, foreground: foreground,
                       background: backgroundEnabled, supported: backgroundSupported, until: policy?.until)
        if session.mode != previous { pending = nil; nextSample = .now }
        let until = isContinuous ? policy?.until : nil
        if until != scheduledUntil {
            expiryTask?.cancel(); expiryTask = nil; scheduledUntil = until
            if let until, until > 0 {
                expiryTask = Task { [weak self] in
                    do { try await Task.sleep(for: .seconds(max(0, until - Date().timeIntervalSince1970))) }
                    catch { return }
                    guard let self, self.scheduledUntil == until else { return }
                    self.session.expireIfNeeded()
                    if !self.session.canSubmit { self.pending = nil }
                }
            }
        }
    }

    func sampleIfDue(_ submit: @escaping ([String: Double]) async -> Void) {
        guard session.mode == .foreground, session.canSubmit, nextSample <= .now, pending == nil else { return }
        nextSample = .now + .seconds(30)
        pending = submit
        manager.requestLocation()
    }

    func suspend() {
        pending = nil; nextSample = .now
        expiryTask?.cancel(); expiryTask = nil; scheduledUntil = nil
        session.stop()
        manager.stopUpdatingLocation()
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        foreground = UIApplication.shared.applicationState == .active
        reconcile()
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        session.expireIfNeeded()
        guard session.canSubmit, UIApplication.shared.applicationState == .active || isContinuous,
              let fix = locations.last, (0...655.35).contains(fix.horizontalAccuracy) else { pending = nil; return }
        let callback: (([String: Double]) async -> Void)?
        if isContinuous {
            guard nextSample <= .now else { return }
            nextSample = .now + .seconds(30)
            callback = submit
        } else { callback = pending; pending = nil }
        guard let callback else { return }
        let fields = [
            "latitude": fix.coordinate.latitude, "longitude": fix.coordinate.longitude,
            "altitude": fix.verticalAccuracy < 0 ? 0 : fix.altitude,
            "speed": max(0, fix.speed), "bearing": max(0, fix.course),
            "accuracy": fix.horizontalAccuracy, "last_update": fix.timestamp.timeIntervalSince1970
        ]
        let generation = session.generation
        Task { [weak self] in
            guard let self, self.session.generation == generation, self.session.canSubmit else { return }
            await callback(fields)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) { pending = nil }
}

struct FamilyLocationMap: View {
    @ObservedObject var family: FamilyModel
    @State private var selected: Int?

    private var contacts: [FamilyContact] {
        (family.state?.contacts ?? []).filter { family.state?.location?.locations[String($0.id)] != nil }
    }

    var body: some View {
        VStack {
            if let layer = family.state?.activeMap, layer != "apple" {
                FamilyOfflineMap(family: family, layer: layer, selection: $selected).id(layer)
                if layer == "pnw" {
                    Text("© OpenStreetMap contributors · Natural Earth · Protomaps (ODbL)")
                        .font(.caption2)
                }
            } else if contacts.isEmpty {
                ContentUnavailableView("No approved locations yet", systemImage: "map")
            } else {
                Map(selection: $selected) {
                    ForEach(contacts) { contact in
                        if let fix = family.state?.location?.locations[String(contact.id)] {
                            Marker(contact.name, coordinate: CLLocationCoordinate2D(
                                latitude: fix.latitude, longitude: fix.longitude
                            ))
                            .tag(contact.id)
                        }
                    }
                }
            }
            if let selected,
               let contact = contacts.first(where: { $0.id == selected }),
               let fix = family.state?.location?.locations[String(selected)] {
                VStack {
                    Text(contact.name).font(.headline)
                    Text("Last updated \(Date(timeIntervalSince1970: fix.last_update), style: .relative) ago")
                }
                .padding(.bottom)
            }
            if let location = family.state?.location, location.userControls {
                FamilyLocationControls(family: family, guardian: false)
                    .padding(.bottom)
            }
        }
        .navigationTitle("Family map")
    }
}

struct FamilyLocationSettings: View {
    @ObservedObject var family: FamilyModel
    @State private var mapEnabled = true
    @State private var userControls = false
    @State private var recipients: Set<Int> = []
    @State private var saved = false
    @State private var backgroundEnabled = false
    @State private var backgroundSaved = false

    private var eligibleContacts: [FamilyContact] {
        (family.state?.contacts ?? []).filter { $0.canShareLocation }
    }

    private var sharingRequirement: String? {
        guard let location = family.state?.location else { return nil }
        if eligibleContacts.isEmpty { return "Add an approved contact with a Reticulum or MeshCore messaging address to share your location." }
        if !mapEnabled { return "Turn on the Family map to share your location." }
        if recipients.isEmpty { return "Turn on at least one contact above and save the location policy." }
        if recipients != Set(location.contactIds) || mapEnabled != location.mapEnabled
            || userControls != location.userControls {
            return "Save the location policy before starting sharing."
        }
        return nil
    }

    var body: some View {
        Form {
            if family.unlocked {
                Section {
                    Toggle("Show Family map", isOn: $mapEnabled)
                    Toggle("Allow timed sharing from the map", isOn: $userControls)
                    if eligibleContacts.isEmpty {
                        NavigationLink("Add approved contact") { FamilyContactApproval(family: family) }
                    }
                    ForEach(eligibleContacts) { contact in
                        Toggle(contact.name, isOn: Binding(
                            get: { recipients.contains(contact.id) },
                            set: { enabled in
                                if enabled { recipients.insert(contact.id) }
                                else { recipients.remove(contact.id) }
                            }
                        ))
                    }
                    Button(saved ? "Location policy saved" : "Save location policy") {
                        Task {
                            saved = await family.saveLocationPolicy(
                                mapEnabled: mapEnabled, userControls: userControls, contactIDs: recipients
                            )
                        }
                    }
                    .onChange(of: mapEnabled) { saved = false }
                    .onChange(of: userControls) { saved = false }
                    .onChange(of: recipients) { saved = false }
                } header: { Text("Approved location contacts") }
                Section {
                    Toggle("Continue sharing with the screen locked", isOn: $backgroundEnabled)
                        .accessibilityIdentifier("location-background-enabled")
                    Button(backgroundSaved ? "Background sharing saved" : "Save background sharing") {
                        Task { backgroundSaved = await family.configureBackgroundLocation(backgroundEnabled) }
                    }
                    .onChange(of: backgroundEnabled) { backgroundSaved = false }
                } header: { Text("Locked-screen sharing") } footer: {
                    Text("Off by default. Start sharing while Family is open. This uses more battery and iOS shows a location indicator. Force-quitting Family ends the location session.")
                }
                Section {
                    FamilyLocationControls(family: family, guardian: true, startRequirement: sharingRequirement)
                }
            }
        }
        .navigationTitle("Location sharing")
        .onAppear {
            backgroundEnabled = family.state?.locationBackgroundEnabled == true
            if let location = family.state?.location {
                mapEnabled = location.mapEnabled
                userControls = location.userControls
                recipients = Set(location.contactIds).intersection(eligibleContacts.map(\.id))
            }
        }
    }
}

struct FamilyLocationControls: View {
    @ObservedObject var family: FamilyModel
    let guardian: Bool
    var startRequirement: String? = nil
    @State private var duration = "15"

    var body: some View {
        if let location = family.state?.location {
            if location.active {
                if location.duration == "ongoing" { Text("Sharing until a guardian stops it") }
                else if location.duration == "60" { Text("Sharing for 1 hour") }
                else { Text("Sharing for 15 minutes") }
                Button("Stop sharing") { Task { await family.stopLocation() } }
            } else {
                Picker("Sharing duration", selection: $duration) {
                    Text("15 minutes").tag("15")
                    Text("1 hour").tag("60")
                    if guardian { Text("Until a guardian stops it").tag("ongoing") }
                }
                Button("Start sharing") { Task { _ = await family.startLocation(duration) } }
                    .disabled(startRequirement != nil || !location.mapEnabled || location.contactIds.isEmpty)
                if let reason = startRequirement ?? (location.contactIds.isEmpty
                    ? "A guardian must approve a location recipient first." : nil) {
                    Text(reason).font(.caption)
                }
            }
            Text(family.state?.locationBackgroundEnabled == true
                 ? "An active sharing session can continue with the screen locked. iOS shows a location indicator."
                 : "Location updates are sent while Family is open.").font(.caption)
            if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
        }
    }
}
