import SwiftUI

/// Build-only host. The physical test explicitly targets the separate neXt preview.
@main
struct DeviceCheckHost: App {
    var body: some Scene { WindowGroup { Text("neXt device checks") } }
}
