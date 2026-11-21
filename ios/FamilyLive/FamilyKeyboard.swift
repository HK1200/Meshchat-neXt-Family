import UIKit

/// Clearing SwiftUI focus alone can leave iPad's keyboard onscreen. Finish
/// editing the actual UIKit responder as well, within this app's own windows.
@MainActor
enum FamilyKeyboard {
    static func dismiss() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        for scene in UIApplication.shared.connectedScenes {
            guard let windowScene = scene as? UIWindowScene else { continue }
            for window in windowScene.windows where window.isKeyWindow { window.endEditing(true) }
        }
    }
}
