import Combine
import Foundation
import Security
import UIKit
import UserNotifications

@MainActor
final class FamilyPushRegistration: ObservableObject {
    private struct Enrollment: Codable, Equatable {
        let provider: URL
        let secret: String
        let recipient: String
        let mailbox: String
        var revoking = false
        var mayBeRegistered: Bool? = false
    }

    private struct Subscription: Encodable, Equatable {
        let recipient: String
        let token: String?
        let senders: [String]

        enum CodingKeys: String, CodingKey {
            case recipient, token, senders
        }

        func encode(to encoder: Encoder) throws {
            var values = encoder.container(keyedBy: CodingKeys.self)
            try values.encode(recipient, forKey: .recipient)
            try values.encode(token, forKey: .token)
            try values.encode(senders, forKey: .senders)
        }
    }

    @Published private(set) var status = "Off"
    @Published private(set) var busy = false
    @Published private var enrollment: Enrollment?
    var configured: Bool { enrollment != nil }
    var stopping: Bool { enrollment?.revoking == true }

    private var deviceToken: String?
    private var senders: [String] = []
    private var registeredThisLaunch = false
    private var lastUpload: Subscription?
    private var retryAfter = Date.distantPast

    init() {
        var query = Self.keychainQuery
        query[kSecReturnData as String] = true
        var item: CFTypeRef?
        if SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
           let data = item as? Data,
           let saved = try? JSONDecoder().decode(Enrollment.self, from: data) {
            enrollment = saved
            status = saved.revoking ? "Turn-off pending" : "Waiting to connect to the alert provider"
        }
    }

    private static var keychainQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "org.meshchat.family.ios.mailbox-alerts",
         kSecAttrAccount as String: "provider-enrollment"]
    }

    private func save(_ value: Enrollment?) -> Bool {
        let query = Self.keychainQuery as CFDictionary
        if let value {
            guard let data = try? JSONEncoder().encode(value) else { return false }
            let update = [kSecValueData as String: data]
            let result = SecItemUpdate(query, update as CFDictionary)
            if result == errSecItemNotFound {
                var item = Self.keychainQuery
                item[kSecValueData as String] = data
                item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
                guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { return false }
            } else if result != errSecSuccess {
                return false
            }
        } else {
            let result = SecItemDelete(query)
            guard result == errSecSuccess || result == errSecItemNotFound else { return false }
        }
        enrollment = value
        return true
    }

    func enable(provider: String, secret: String, state: FamilyReply?, guardianUnlocked: () -> Bool) async {
        guard enrollment == nil, !busy,
              let recipient = state?.address, recipient.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              let mailbox = state?.mailbox?.address, !mailbox.isEmpty else {
            status = "Save an offline mailbox and wait for your Reticulum identity before enabling alerts."
            return
        }
        let code = secret.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard let parts = URLComponents(string: provider.trimmingCharacters(in: .whitespacesAndNewlines)),
              parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              let address = parts.url,
              code.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            status = "Enter an HTTPS provider address and its 64-character enrollment code."
            return
        }
        busy = true
        let center = UNUserNotificationCenter.current()
        guard (try? await center.requestAuthorization(options: [.alert, .sound])) == true else {
            busy = false
            status = "Allow Family notifications in iPadOS Settings, then try again."
            return
        }
        busy = false
        guard guardianUnlocked() else { return }
        guard save(Enrollment(provider: address, secret: code, recipient: recipient, mailbox: mailbox)) else {
            status = "Family couldn’t save the enrollment code in Keychain."
            return
        }
        senders = Self.approvedKeys(state?.contacts ?? [])
        requestToken()
    }

    private static func approvedKeys(_ contacts: [FamilyContact]) -> [String] {
        Array(Set(contacts.compactMap { contact in
            guard let key = contact.identityPublicKey?.lowercased(),
                  key.range(of: "^[a-f0-9]{128}$", options: .regularExpression) != nil,
                  contact.addresses["lxmf"]?.isEmpty == false else { return nil as String? }
            return key
        })).sorted()
    }

    func refresh(_ state: FamilyReply) {
        guard let enrollment else { return }
        if !enrollment.revoking, let recipient = state.address, !recipient.isEmpty,
           recipient != enrollment.recipient || state.mailbox?.address != enrollment.mailbox {
            disable()
            return
        }
        senders = Self.approvedKeys(state.contacts ?? [])
        if !enrollment.revoking, !registeredThisLaunch {
            requestToken()
        }
        sync()
    }

    private func requestToken() {
        registeredThisLaunch = true
        status = "Waiting for Apple push registration"
        UIApplication.shared.registerForRemoteNotifications()
    }

    func receivedToken(_ data: Data) {
        guard enrollment?.revoking == false else { return }
        deviceToken = data.map { String(format: "%02x", $0) }.joined()
        retryAfter = .distantPast
        sync()
    }

    func registrationFailed() {
        guard enrollment?.revoking == false else { return }
        status = "Apple push registration failed. Retry online with a push-enabled Family build."
    }

    func retry() {
        guard enrollment != nil else { return }
        retryAfter = .distantPast
        if enrollment?.revoking == false && deviceToken == nil {
            requestToken()
        } else {
            sync()
        }
    }

    func disable() {
        guard var current = enrollment else { return }
        if current.mayBeRegistered == false {
            guard save(nil) else {
                status = "Family couldn’t remove the local push setup."
                return
            }
            UIApplication.shared.unregisterForRemoteNotifications()
            deviceToken = nil
            registeredThisLaunch = false
            lastUpload = nil
            status = "Off"
            return
        }
        current.revoking = true
        guard save(current) else {
            status = "Family couldn’t save the request to turn alerts off."
            return
        }
        UIApplication.shared.unregisterForRemoteNotifications()
        deviceToken = nil
        status = "Turn-off pending"
        retryAfter = .distantPast
        sync()
    }

    private func sync() {
        guard var current = enrollment, !busy, Date() >= retryAfter,
              current.revoking || deviceToken != nil else { return }
        if !current.revoking, current.mayBeRegistered == false {
            // Persist this before the request so a crash cannot skip remote revocation.
            current.mayBeRegistered = true
            guard save(current) else {
                status = "Family couldn’t save the provider registration state."
                retryAfter = Date().addingTimeInterval(30)
                return
            }
        }
        let enrollment = current
        let request = Subscription(recipient: enrollment.recipient,
                                   token: enrollment.revoking ? nil : deviceToken,
                                   senders: enrollment.revoking ? [] : senders)
        guard request != lastUpload || enrollment.revoking else { return }
        busy = true
        Task {
            defer {
                busy = false
                if self.enrollment != enrollment { sync() }
            }
            do {
                var upload = URLRequest(url: enrollment.provider.appendingPathComponent("v1").appendingPathComponent("subscription"))
                upload.httpMethod = "POST"
                upload.timeoutInterval = 12
                upload.setValue("application/json", forHTTPHeaderField: "Content-Type")
                upload.setValue("Bearer " + enrollment.secret, forHTTPHeaderField: "Authorization")
                upload.httpBody = try JSONEncoder().encode(request)
                let (_, response) = try await URLSession.shared.data(for: upload, delegate: NoRedirect())
                guard (response as? HTTPURLResponse)?.statusCode == 204 else { throw URLError(.badServerResponse) }
                lastUpload = request
                guard self.enrollment == enrollment else { return }
                if enrollment.revoking {
                    status = save(nil) ? "Off" : "Provider disabled. Tap Retry to clear local setup."
                    registeredThisLaunch = false
                    lastUpload = nil
                } else {
                    status = "On"
                }
            } catch {
                retryAfter = Date().addingTimeInterval(30)
                guard self.enrollment == enrollment else {
                    retryAfter = .distantPast
                    return
                }
                status = enrollment.revoking ? "Turn-off pending. Provider unavailable." :
                    "Provider setup pending. Check the address or enrollment code and retry."
            }
        }
    }
}

private final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest) async -> URLRequest? { nil }
}
