import SwiftUI
import UIKit
import WebKit

@main
struct FamilyPreviewApp: App {
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 0) {
                Text("iOS preview · Sample data only")
                    .font(.footnote.weight(.semibold))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity)
                    .background(.thinMaterial)
                    .accessibilityAddTraits(.isHeader)

                if let assets = Bundle.main.url(forResource: "assets", withExtension: nil) {
                    FamilyWebView(assets: assets)
                } else {
                    ContentUnavailableView(
                        "Family interface unavailable",
                        systemImage: "folder",
                        description: Text("The preview bundle is missing its Family assets.")
                    )
                }
            }
        }
    }
}

private struct FamilyWebView: UIViewRepresentable {
    let assets: URL

    func makeCoordinator() -> Coordinator {
        Coordinator(assets: assets)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(context.coordinator, name: "previewTheme")
        let savedTheme = UserDefaults.standard.string(forKey: "previewTheme")
        let theme = savedTheme == "night" ? "night" : savedTheme == "day" ? "day" : ""
        configuration.userContentController.addUserScript(WKUserScript(
            source: "try { localStorage.setItem('next-family-theme', '\(theme)'); } catch {}",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        configuration.setURLSchemeHandler(context.coordinator, forURLScheme: FamilyAssets.scheme)
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.defaultWebpagePreferences.preferredContentMode = .mobile
        if let script = Self.layoutScript() {
            configuration.userContentController.addUserScript(script)
        }

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.load(URLRequest(url: FamilyAssets.entryPoint))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    private static func layoutScript() -> WKUserScript? {
        guard let url = Bundle.main.url(forResource: "FamilyPreview", withExtension: "css"),
              let css = try? String(contentsOf: url, encoding: .utf8),
              let encoded = try? JSONEncoder().encode(css),
              let literal = String(data: encoded, encoding: .utf8) else {
            return nil
        }
        let source = """
            if (location.href === "family://bundle/index.html") {
                const style = document.createElement("style");
                style.textContent = \(literal);
                document.head.appendChild(style);
                document.getElementById("theme-toggle").addEventListener("click", () => {
                    window.webkit.messageHandlers.previewTheme.postMessage(document.documentElement.dataset.theme);
                });
            }
            """
        return WKUserScript(source: source, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKURLSchemeHandler, WKScriptMessageHandler {
        private let assets: FamilyAssets

        init(assets: URL) {
            self.assets = FamilyAssets(directory: assets)
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "previewTheme", message.frameInfo.isMainFrame,
                  message.frameInfo.request.url == FamilyAssets.entryPoint,
                  let theme = message.body as? String, ["day", "night"].contains(theme) else {
                return
            }
            UserDefaults.standard.set(theme, forKey: "previewTheme")
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            let allowed = navigationAction.targetFrame?.isMainFrame == true
                && navigationAction.request.url == FamilyAssets.entryPoint
            decisionHandler(allowed ? .allow : .cancel)
        }

        func webView(
            _ webView: WKWebView,
            runJavaScriptAlertPanelWithMessage message: String,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping () -> Void
        ) {
            guard frame.isMainFrame, frame.request.url == FamilyAssets.entryPoint,
                  let presenter = webView.window?.rootViewController,
                  presenter.presentedViewController == nil else {
                completionHandler()
                return
            }
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            presenter.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
            do {
                let (response, data) = try assets.response(to: task.request)
                task.didReceive(response)
                task.didReceive(data)
                task.didFinish()
            } catch {
                task.didFailWithError(error)
            }
        }

        func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {
            // The handler completes each local read before returning.
        }
    }
}
