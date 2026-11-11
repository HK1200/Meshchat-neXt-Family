import MapKit
import SwiftUI
import UniformTypeIdentifiers

struct FamilyOfflineMapSettings: View {
    @ObservedObject var family: FamilyModel
    @State private var choosingFile = false
    @State private var importing = false
    @State private var removal: FamilyMapPack?

    var body: some View {
        Form {
            if family.unlocked {
                Section("Map layer") {
                    layer("Apple Maps", id: "apple")
                    layer("Pacific Northwest and southern BC", id: "pnw")
                    ForEach(family.state?.mapPacks ?? []) { pack in
                        layer(pack.name, id: pack.id)
                            .swipeActions {
                                Button("Remove", role: .destructive) { removal = pack }
                            }
                    }
                }
                Section {
                    Button("Import MBTiles map", systemImage: "square.and.arrow.down") { choosingFile = true }
                        .disabled(importing)
                    if importing { ProgressView("Importing map") }
                    if !family.error.isEmpty { Text(family.error).foregroundStyle(.red) }
                } footer: {
                    Text("Choose a raster MBTiles pack from Files. Imported maps stay on this device.")
                }
            }
        }
        .navigationTitle("Offline maps")
        .fileImporter(isPresented: $choosingFile, allowedContentTypes: [.data]) { result in
            switch result {
            case .success(let url):
                importing = true
                Task {
                    _ = await family.importMap(url)
                    importing = false
                }
            case .failure(let error): family.error = error.localizedDescription
            }
        }
        .confirmationDialog("Remove offline map?", isPresented: Binding(
            get: { removal != nil }, set: { if !$0 { removal = nil } }
        ), titleVisibility: .visible, presenting: removal) { pack in
            Button("Remove \(pack.name)", role: .destructive) {
                Task { _ = await family.removeMap(pack.id) }
            }
        }
    }

    private func layer(_ name: String, id: String) -> some View {
        Button {
            Task { _ = await family.selectMap(id) }
        } label: {
            HStack {
                Text(name)
                Spacer()
                if family.state?.activeMap == id { Image(systemName: "checkmark").accessibilityLabel("Selected") }
            }
        }
        .disabled(importing)
        .accessibilityIdentifier("offline-map-layer-\(id)")
        .accessibilityValue(family.state?.activeMap == id ? "Selected" : "")
    }
}

struct FamilyOfflineMap: UIViewRepresentable {
    @ObservedObject var family: FamilyModel
    let layer: String
    @Binding var selection: Int?

    func makeCoordinator() -> Coordinator { Coordinator(selection: $selection) }

    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.delegate = context.coordinator
        map.isPitchEnabled = false
        map.isRotateEnabled = false
        let pack = family.state?.mapPacks?.first { $0.id == layer }
        let overlay = OfflineTileOverlay(family: family, layer: layer, pack: pack)
        map.addOverlay(overlay, level: .aboveLabels)
        let first = (family.state?.contacts ?? []).compactMap { family.state?.location?.locations[String($0.id)] }.first
        let center = CLLocationCoordinate2D(latitude: first?.latitude ?? pack?.center?.lat ?? 47.5,
                                            longitude: first?.longitude ?? pack?.center?.lon ?? -122)
        map.setRegion(MKCoordinateRegion(center: center, span: MKCoordinateSpan(latitudeDelta: 3, longitudeDelta: 3)), animated: false)
        return map
    }

    func updateUIView(_ map: MKMapView, context: Context) {
        let contacts = family.state?.contacts ?? []
        let locations = family.state?.location?.locations ?? [:]
        context.coordinator.update(map, contacts: contacts, locations: locations)
    }

    @MainActor
    final class Coordinator: NSObject, @preconcurrency MKMapViewDelegate {
        private let selection: Binding<Int?>
        private var pins: [Int: FamilyMapAnnotation] = [:]

        init(selection: Binding<Int?>) { self.selection = selection }

        func update(_ map: MKMapView, contacts: [FamilyContact], locations: [String: FamilyLocationFix]) {
            let visible = Set(contacts.filter { locations[String($0.id)] != nil }.map(\.id))
            for id in Set(pins.keys).subtracting(visible) {
                if let removed = pins.removeValue(forKey: id) { map.removeAnnotation(removed) }
            }
            for contact in contacts {
                guard let fix = locations[String(contact.id)] else { continue }
                let coordinate = CLLocationCoordinate2D(latitude: fix.latitude, longitude: fix.longitude)
                if let pin = pins[contact.id] {
                    if pin.coordinate.latitude != coordinate.latitude || pin.coordinate.longitude != coordinate.longitude {
                        pin.coordinate = coordinate
                    }
                    if pin.title != contact.name { pin.title = contact.name }
                } else {
                    let pin = FamilyMapAnnotation(contactID: contact.id)
                    pin.title = contact.name
                    pin.coordinate = coordinate
                    pins[contact.id] = pin
                    map.addAnnotation(pin)
                }
            }
        }

        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let tiles = overlay as? MKTileOverlay { return MKTileOverlayRenderer(tileOverlay: tiles) }
            return MKOverlayRenderer(overlay: overlay)
        }

        func mapView(_ mapView: MKMapView, didSelect view: MKAnnotationView) {
            if let pin = view.annotation as? FamilyMapAnnotation { selection.wrappedValue = pin.contactID }
        }
    }
}

private final class FamilyMapAnnotation: MKPointAnnotation {
    let contactID: Int
    init(contactID: Int) { self.contactID = contactID; super.init() }
}

private final class OfflineTileOverlay: MKTileOverlay {
    private weak var family: FamilyModel?
    private let layer: String

    init(family: FamilyModel, layer: String, pack: FamilyMapPack?) {
        self.family = family
        self.layer = layer
        super.init(urlTemplate: nil)
        minimumZ = pack?.minZoom ?? 0
        maximumZ = pack?.maxZoom ?? 9
        canReplaceMapContent = true
    }

    override func loadTile(at path: MKTileOverlayPath, result: @escaping @Sendable (Data?, Error?) -> Void) {
        if layer == "pnw" {
            let url = Bundle.main.resourceURL?.appendingPathComponent("pnw-tiles/\(path.z)/\(path.x)/\(path.y).png")
            result(url.flatMap { try? Data(contentsOf: $0) }, nil)
            return
        }
        let layer = layer
        Task { [weak family] in
            do { result(try await family?.mapTile(id: layer, x: path.x, y: path.y, z: path.z), nil) }
            catch { result(nil, error) }
        }
    }
}
