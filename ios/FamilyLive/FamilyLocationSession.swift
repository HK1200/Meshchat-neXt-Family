import Foundation

/// A sharing session may continue while locked only if it began in the foreground.
@MainActor
final class FamilyLocationSession {
    enum Mode: Equatable { case off, foreground, continuous }
    private let startContinuous: () -> Void
    private let stopContinuous: () -> Void
    private let now: () -> TimeInterval
    private var active = false
    private var authorized = false
    private var foreground = false
    private var until: TimeInterval?
    private(set) var mode: Mode = .off
    private(set) var generation = 0

    init(now: @escaping () -> TimeInterval = { Date().timeIntervalSince1970 },
         start: @escaping () -> Void, stop: @escaping () -> Void) {
        self.now = now; startContinuous = start; stopContinuous = stop
    }

    var canSubmit: Bool {
        active && authorized && isCurrent && mode != .off && (foreground || mode == .continuous)
    }
    private var isCurrent: Bool { until == -1 || (until.map { $0.isFinite && $0 > now() } ?? false) }

    func update(active: Bool, authorized: Bool, foreground: Bool, background: Bool,
                supported: Bool, until: TimeInterval?) {
        self.active = active; self.authorized = authorized; self.foreground = foreground; self.until = until
        let desired: Mode
        if !active || !authorized || !isCurrent { desired = .off }
        else if background && supported && (foreground || mode == .continuous) { desired = .continuous }
        else { desired = foreground ? .foreground : .off }
        transition(desired)
    }

    func expireIfNeeded() { if !isCurrent { transition(.off) } }
    func stop() { active = false; transition(.off) }

    private func transition(_ desired: Mode) {
        guard mode != desired else { return }
        let previous = mode
        mode = desired
        generation += 1
        if previous == .continuous { stopContinuous() }
        if desired == .continuous { startContinuous() }
    }
}
