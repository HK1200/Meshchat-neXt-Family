// SPDX-License-Identifier: 0BSD
import Foundation

/// Only a disposable simulator can suppress automatic UI/backend startup while
/// XCTest exercises models. Physical apps and ordinary UI tests ignore this.
enum NextNativeModelHost {
    static func enabled(simulator: Bool, fixturePresent: Bool, environment: [String: String]) -> Bool {
        simulator && fixturePresent && environment["NEXT_NATIVE_MODEL_HOST"] == "1"
    }
    static var active: Bool {
        #if targetEnvironment(simulator)
        let fixture = Bundle.main.resourceURL?.appendingPathComponent("staged/peer.json")
        return enabled(simulator: true, fixturePresent: fixture.map { FileManager.default.fileExists(atPath: $0.path) } ?? false,
                       environment: ProcessInfo.processInfo.environment)
        #else
        return false
        #endif
    }
}
