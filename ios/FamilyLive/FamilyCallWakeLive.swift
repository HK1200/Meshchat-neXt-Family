// SPDX-License-Identifier: 0BSD
import AVFAudio
import Foundation

@MainActor private struct FamilyNativeCallWakeGate: FamilyCallWakeArming {
    func arm(_ call: UUID, voice: String, seconds: UInt32) -> Bool {
        family_call_wake_arm(call.uuidString.replacingOccurrences(of: "-", with: "").lowercased(), voice, seconds)
    }
    func cancel(_ call: UUID) {
        family_call_wake_cancel(call.uuidString.replacingOccurrences(of: "-", with: "").lowercased())
    }
    func reset() { family_call_wake_reset() }
}

@MainActor extension FamilyCallWakeOwner {
    static var liveEligible: Bool {
        #if targetEnvironment(simulator)
        return false
        #else
        guard !ProcessInfo.processInfo.arguments.contains("--isolated-family-test") else { return false }
        let value = Bundle.main.object(forInfoDictionaryKey: "FamilyPushEnvironment") as? String
        return value == "development" || value == "production"
        #endif
    }
    static let shared = FamilyCallWakeOwner(system: .shared, runtime: FamilyModel.shared,
        gate: FamilyNativeCallWakeGate(), directory: {
            try FileManager.default.url(for: .applicationSupportDirectory,
                in: .userDomainMask, appropriateFor: nil, create: false)
        }, eligible: { FamilyCallWakeOwner.liveEligible },
        permissions: { AVAudioApplication.shared.recordPermission == .granted },
        store: NextCallWakeEnrollmentKeychain(), uploader: NextPushHTTPS(), query: NextCallWakeQuery())
}
