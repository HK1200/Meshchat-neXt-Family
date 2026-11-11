import CoreLocation
import MapKit
import SwiftUI

@MainActor
final class FamilyLocationSampler: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var nextSample = ContinuousClock.now
    private var pending: (([String: Double]) async -> Void)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
    }

    func requestPermission() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
    }

    func sampleIfDue(_ submit: @escaping ([String: Double]) async -> Void) {
        guard manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways,
              nextSample <= .now, pending == nil else { return }
        nextSample = .now + .seconds(30)
        pending = submit
        manager.requestLocation()
    }

    func suspend() {
        pending = nil
        nextSample = .now
        manager.stopUpdatingLocation()
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let submit = pending
        pending = nil
        guard let submit, let fix = locations.last, (0...655.35).contains(fix.horizontalAccuracy) else { return }
        let fields = [
            "latitude": fix.coordinate.latitude, "longitude": fix.coordinate.longitude,
            "altitude": fix.verticalAccuracy < 0 ? 0 : fix.altitude,
            "speed": max(0, fix.speed), "bearing": max(0, fix.course),
            "accuracy": fix.horizontalAccuracy, "last_update": fix.timestamp.timeIntervalSince1970
        ]
        Task { await submit(fields) }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        pending = nil
    }
}

struct FamilyLocationMap: View {
    @ObservedObject var family: FamilyModel
    @State private var selected: Int?

    private var contacts: [FamilyContact] {
        (family.state?.contacts ?? []).filter { family.state?.location?.locations[String($0.id)] != nil }
    }

    var body: some View {
        VStack {
            if contacts.isEmpty {
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
                if let selected,
                   let contact = contacts.first(where: { $0.id == selected }),
                   let fix = family.state?.location?.locations[String(selected)] {
                    VStack {
                        Text(contact.name).font(.headline)
                        Text("Last updated \(Date(timeIntervalSince1970: fix.last_update), style: .relative) ago")
                    }
                    .padding(.bottom)
                }
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

    var body: some View {
        Form {
            if family.unlocked {
                Section {
                    Toggle("Show Family map", isOn: $mapEnabled)
                    Toggle("Allow timed sharing from the map", isOn: $userControls)
                    ForEach(family.state?.contacts ?? []) { contact in
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
                    FamilyLocationControls(family: family, guardian: true)
                }
            }
        }
        .navigationTitle("Location sharing")
        .onAppear {
            if let location = family.state?.location {
                mapEnabled = location.mapEnabled
                userControls = location.userControls
                recipients = Set(location.contactIds)
            }
        }
    }
}

struct FamilyLocationControls: View {
    @ObservedObject var family: FamilyModel
    let guardian: Bool
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
                    .disabled(!location.mapEnabled || location.contactIds.isEmpty)
            }
            Text("Location updates are sent while Family is open.").font(.caption)
            if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
        }
    }
}
