import Foundation
import WebKit

@MainActor
final class NextWebPreferencesBridge: NSObject, WKScriptMessageHandlerWithReply {
    private let base: URL
    private let preferences: NextWebPreferences?
    private let onError: () -> Void
    init(base: URL, folder: URL, onError: @escaping () -> Void) {
        self.base = base; self.preferences = try? NextWebPreferences(folder: folder); self.onError = onError
        super.init()
    }
    func install(in configuration: WKWebViewConfiguration) throws {
        guard let file = Bundle.main.url(forResource: "next-web-preferences", withExtension: "js") else { throw CocoaError(.fileNoSuchFile) }
        let source = try String(contentsOf: file, encoding: .utf8)
        let payload: [String: Any] = ["origin": "http://127.0.0.1:\(base.port ?? 0)",
                                      "keys": NextWebPreferences.keys.sorted(), "values": preferences?.values ?? [:]]
        let encoded = String(decoding: try JSONSerialization.data(withJSONObject: payload), as: UTF8.self)
        configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "nextPreferences")
        configuration.userContentController.addUserScript(WKUserScript(source: "(\(source))(\(encoded));",
            injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let origin = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame, origin.protocol == "http", origin.host == "127.0.0.1", origin.port == base.port,
              let value = message.body as? [String: Any] else {
            replyHandler(nil, "Unavailable"); return
        }
        do {
            guard let preferences else { throw CocoaError(.fileReadCorruptFile) }
            try preferences.apply(value)
            replyHandler(true, nil)
        } catch {
            onError()
            replyHandler(nil, "The preference could not be saved")
        }
    }
}
