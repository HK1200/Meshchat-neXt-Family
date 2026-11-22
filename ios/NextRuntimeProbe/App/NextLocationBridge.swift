import CoreLocation
import Foundation
import UIKit

/// Location is idle until an explicit foreground sharing action. The interpreter
/// receives a fix only while the current native consent generation permits it.
@MainActor
final class NextLocationBridge: NSObject, @preconcurrency CLLocationManagerDelegate {
    private static let shared = NextLocationBridge()
    private let manager = CLLocationManager()
    private var token: String?
    private var command: NextLocationCommand?
    private var lastFix: [String: Double]?
    private var error = ""
    private var sampling = false
    private var nextSample = ContinuousClock.now
    private var timer: Timer?
    private let grants = NextLocationGrants()
    private lazy var policy = FamilyLocationSession(start: {}, stop: { [weak self] in self?.stopSampling() })
    private var foreground: Bool { UIApplication.shared.applicationState == .active }
    private var supported: Bool {
        (Bundle.main.object(forInfoDictionaryKey: "UIBackgroundModes") as? [String])?.contains("location") == true
    }
    private var authorized: Bool {
        manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways
    }

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        for name in [UIApplication.didBecomeActiveNotification, UIApplication.didEnterBackgroundNotification] {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.reconcile() }
            }
        }
    }

    nonisolated static func request(_ text: String) -> String {
        guard text.utf8.count <= 16_384 else { return "{\"ok\":false}" }
        let operation = { @MainActor in shared.perform(text) }
        if Thread.isMainThread { return MainActor.assumeIsolated { operation() } }
        return DispatchQueue.main.sync { MainActor.assumeIsolated { operation() } }
    }

    private func perform(_ text: String) -> String {
        do {
            guard let data = text.data(using: .utf8),
                  let raw = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return "{\"ok\":false}"
            }
            let request = try NextLocationCommand(raw)
            let reply = perform(request)
            return String(decoding: try JSONSerialization.data(withJSONObject: reply), as: UTF8.self)
        } catch { return "{\"ok\":false,\"error\":\"Invalid location request\"}" }
    }

    private func perform(_ request: NextLocationCommand) -> [String: Any] {
        switch request.operation {
        case .start, .resume:
            guard foreground else { return ["ok": false, "error": "Open neXt before starting location sharing."] }
            if request.operation == .resume {
                guard grants.permitsResume(request.revisions) else {
                    return ["ok": false, "error": "Start sharing again to confirm the recipients."]
                }
            }
            token = request.session; command = request; error = ""; lastFix = nil
            grants.replace(with: request.revisions)
            if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
            startTimer(); reconcile()
        case .configure:
            guard token == request.session else { return ["ok": false] }
            command = request
            grants.replace(with: request.revisions)
            reconcile()
        case .stop, .suspend:
            guard token == nil || token == request.session else { return ["ok": false] }
            if request.operation == .stop { grants.revoke() }
            command = nil; lastFix = nil; policy.stop(); stopSampling()
            timer?.invalidate(); timer = nil
        case .status:
            guard token == request.session else {
                return ["ok": true, "can_submit": false, "generation": policy.generation]
            }
            reconcile()
        }
        var result: [String: Any] = ["ok": true, "can_submit": policy.canSubmit,
            "generation": policy.generation, "background_supported": supported,
            "authorized": authorized, "error": error]
        if policy.canSubmit, let lastFix { result["fix"] = lastFix }
        return result
    }

    private func startTimer() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.reconcile() }
        }
    }
    private func stopSampling() {
        manager.stopUpdatingLocation(); sampling = false
        manager.allowsBackgroundLocationUpdates = false
        manager.showsBackgroundLocationIndicator = false
    }
    private func reconcile() {
        if command?.active == true && !authorized && manager.authorizationStatus != .notDetermined {
            error = "Allow location in iOS Settings before sharing device location."
        }
        let previous = policy.generation
        policy.update(active: command?.active == true, authorized: authorized, foreground: foreground,
                      background: command?.background == true, supported: supported, until: command?.until)
        policy.expireIfNeeded()
        if previous != policy.generation { lastFix = nil; nextSample = .now }
        switch policy.mode {
        case .off:
            stopSampling(); lastFix = nil
        case .continuous:
            if !sampling {
                manager.allowsBackgroundLocationUpdates = true
                manager.showsBackgroundLocationIndicator = true
                manager.pausesLocationUpdatesAutomatically = false
                manager.startUpdatingLocation(); sampling = true
            }
        case .foreground:
            if sampling { stopSampling() }
            if nextSample <= .now {
                nextSample = .now + .seconds(30)
                manager.requestLocation()
            }
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) { reconcile() }
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        policy.expireIfNeeded()
        guard policy.canSubmit, foreground || policy.mode == .continuous,
              let fix = locations.last, abs(fix.timestamp.timeIntervalSinceNow) <= 120 else { return }
        guard (0...655.35).contains(fix.horizontalAccuracy) else {
            error = "Waiting for an accurate fix. Enable Precise Location for neXt if it is off."
            lastFix = nil; return
        }
        lastFix = ["latitude": fix.coordinate.latitude, "longitude": fix.coordinate.longitude,
                   "altitude": fix.verticalAccuracy < 0 ? 0 : fix.altitude,
                   "accuracy": fix.horizontalAccuracy, "speed": max(0, fix.speed),
                   "bearing": max(0, fix.course), "last_update": fix.timestamp.timeIntervalSince1970]
        error = ""
    }
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        self.error = "Waiting for a fresh location fix."
        lastFix = nil
    }
}
