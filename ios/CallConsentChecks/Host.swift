// SPDX-License-Identifier: 0BSD
import SwiftUI

// Disposable simulator host only: no runtime, permissions, radio or APNs.
// A real foreground window scene also hosts the actual WebKit readiness tests.
@main @MainActor struct CallConsentHost: App {
    var body: some Scene { WindowGroup { Color.clear } }
}
