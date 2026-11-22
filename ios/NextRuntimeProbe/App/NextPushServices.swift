import Foundation
import Security
import UIKit
import UserNotifications

struct NextPushContact: Decodable {
    let name: String?
    let identityPublicKey: String?
    let addresses: [String: String]
}
struct NextPushState: Decodable {
    struct Mailbox: Decodable { let address: String }
    let address: String?
    let mailbox: Mailbox?
    let contacts: [NextPushContact]?
}

@MainActor protocol NextPushStoring {
    func load() -> Data?
    func save(_ data: Data?) -> Bool
}
@MainActor protocol NextPushUploading {
    func upload(_ request: URLRequest) async throws -> Int
}
@MainActor protocol NextPushDevice {
    func authorize() async throws -> Bool
    func register()
    func unregister()
}

@MainActor struct NextApplePushDevice: NextPushDevice {
    func authorize() async throws -> Bool {
        try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
    }
    func register() { UIApplication.shared.registerForRemoteNotifications() }
    func unregister() { UIApplication.shared.unregisterForRemoteNotifications() }
}

@MainActor struct NextPushKeychain: NextPushStoring {
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "org.meshchat.next.ios.mailbox-alerts",
         kSecAttrAccount as String: "provider-enrollment"]
    }
    func load() -> Data? {
        var request = query; request[kSecReturnData as String] = true
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }
    func save(_ data: Data?) -> Bool {
        guard let data else {
            let status = SecItemDelete(query as CFDictionary)
            return status == errSecSuccess || status == errSecItemNotFound
        }
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var value = query; value[kSecValueData as String] = data
        value[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(value as CFDictionary, nil) == errSecSuccess
    }
}

@MainActor final class NextPushHTTPS: NextPushUploading {
    private let session: URLSession
    init() {
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false; config.httpCookieStorage = nil
        config.urlCredentialStorage = nil; config.urlCache = nil
        config.timeoutIntervalForRequest = 12; config.timeoutIntervalForResource = 15
        session = URLSession(configuration: config, delegate: NextPushNoRedirect(), delegateQueue: nil)
    }
    deinit { session.invalidateAndCancel() }
    func upload(_ request: URLRequest) async throws -> Int {
        guard let url = request.url, url.scheme?.lowercased() == "https", url.host != nil,
              url.user == nil, url.password == nil else { throw URLError(.badURL) }
        let (_, response) = try await session.data(for: request)
        return (response as? HTTPURLResponse)?.statusCode ?? 0
    }
}
private final class NextPushNoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
