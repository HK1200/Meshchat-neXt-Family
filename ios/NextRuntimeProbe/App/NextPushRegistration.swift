import Combine
import Foundation

@MainActor
final class NextPushRegistration: ObservableObject {
    private struct Enrollment: Codable, Equatable {
        let provider: URL
        let secret: String
        let recipient: String
        let mailbox: String
        var revoking = false
        var mayBeRegistered: Bool? = false
        var allowedAddresses: [String]? = nil
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
    var allowedAddresses: Set<String> { Set(enrollment?.allowedAddresses ?? []) }

    private var lastKnownState: NextPushState?
    private var deviceToken: String?
    private var senders: [String] = []
    private var registeredThisLaunch = false
    private var lastUpload: Subscription?
    private var retryAfter = Date.distantPast

    private let store: any NextPushStoring
    private let uploader: any NextPushUploading
    private let device: any NextPushDevice
    private let now: () -> Date

    init(store: (any NextPushStoring)? = nil, uploader: (any NextPushUploading)? = nil,
         device: (any NextPushDevice)? = nil, now: @escaping () -> Date = { Date() }) {
        self.store = store ?? NextPushKeychain()
        self.uploader = uploader ?? NextPushHTTPS()
        self.device = device ?? NextApplePushDevice()
        self.now = now
        if let data = self.store.load(), let saved = try? JSONDecoder().decode(Enrollment.self, from: data) {
            enrollment = saved
            status = saved.revoking ? "Turn-off pending" : "Waiting to connect to the alert provider"
        }
    }

    private func save(_ value: Enrollment?) -> Bool {
        let data: Data?
        if let value {
            guard let encoded = try? JSONEncoder().encode(value) else { return false }
            data = encoded
        } else { data = nil }
        guard store.save(data) else { return false }
        enrollment = value
        return true
    }

    func enable(provider: String, secret: String, state incoming: NextPushState?, allowedAddresses: Set<String>, stillPermitted: () -> Bool) async {
        let state = lastKnownState ?? incoming
        guard enrollment == nil, !busy,
              let recipient = state?.address, recipient.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              let mailbox = state?.mailbox?.address, mailbox.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else {
            status = "Save an offline mailbox and wait for your Reticulum identity before enabling alerts."
            return
        }
        let code = secret.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard let parts = URLComponents(string: provider.trimmingCharacters(in: .whitespacesAndNewlines)),
              parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              parts.port == nil || (1...65535).contains(parts.port!),
              let address = parts.url,
              code.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            status = "Enter an HTTPS provider address and its 64-character enrollment code."
            return
        }
        guard Self.validSelection(allowedAddresses, state: state) else {
            status = "Select up to 256 saved contacts with verified Reticulum identities."
            return
        }
        busy = true
        guard (try? await device.authorize()) == true else {
            busy = false
            status = "Allow neXt notifications in Settings, then try again."
            return
        }
        busy = false
        let latest = lastKnownState ?? state
        guard stillPermitted(), latest?.address == recipient, latest?.mailbox?.address == mailbox,
              Self.validSelection(allowedAddresses, state: latest) else {
            status = "The mailbox, identity or contact approval changed. Review settings and try again."
            return
        }
        guard save(Enrollment(provider: address, secret: code, recipient: recipient, mailbox: mailbox,
                              allowedAddresses: allowedAddresses.sorted())) else {
            status = "neXt couldn’t save the enrollment code in Keychain."
            return
        }
        senders = Self.approvedKeys(latest?.contacts ?? [], addresses: allowedAddresses)
        requestToken()
    }

    private static func validSelection(_ selected: Set<String>, state: NextPushState?) -> Bool {
        let valid = Set((state?.contacts ?? []).compactMap { contact -> String? in
            guard let key = contact.identityPublicKey, key.range(of: "^[a-f0-9]{128}$", options: .regularExpression) != nil,
                  let address = contact.addresses["lxmf"], address.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { return nil }
            return address
        })
        return selected.count <= 256 && selected.isSubset(of: valid)
    }

    func updateAllowedContacts(_ selected: Set<String>, state incoming: NextPushState, stillPermitted: () -> Bool) {
        let state = lastKnownState ?? incoming
        guard var current = enrollment, !current.revoking, !busy, stillPermitted(),
              Self.validSelection(selected, state: state) else { return }
        current.allowedAddresses = selected.sorted()
        guard save(current) else { status = "neXt couldn’t save the selected contacts."; return }
        senders = Self.approvedKeys(state.contacts ?? [], addresses: selected)
        retryAfter = .distantPast
        sync()
    }

    private static func approvedKeys(_ contacts: [NextPushContact], addresses: Set<String>) -> [String] {
        Array(Set(contacts.compactMap { contact in
            guard let key = contact.identityPublicKey?.lowercased(),
                  key.range(of: "^[a-f0-9]{128}$", options: .regularExpression) != nil,
                  let address = contact.addresses["lxmf"], addresses.contains(address) else { return nil as String? }
            return key
        })).sorted()
    }

    func refresh(_ state: NextPushState) {
        lastKnownState = state
        guard let enrollment else { return }
        if !enrollment.revoking, let recipient = state.address, !recipient.isEmpty,
           recipient != enrollment.recipient || state.mailbox?.address != enrollment.mailbox {
            disable()
            return
        }
        senders = Self.approvedKeys(state.contacts ?? [], addresses: Set(enrollment.allowedAddresses ?? []))
        if !enrollment.revoking, !registeredThisLaunch {
            requestToken()
        }
        sync()
    }

    private func requestToken() {
        registeredThisLaunch = true
        status = "Waiting for Apple push registration"
        device.register()
    }

    func receivedToken(_ data: Data) {
        guard enrollment?.revoking == false else { return }
        guard (16...256).contains(data.count) else { registrationFailed(); return }
        deviceToken = data.map { String(format: "%02x", $0) }.joined()
        retryAfter = .distantPast
        sync()
    }

    func registrationFailed() {
        guard enrollment?.revoking == false else { return }
        status = "Apple push registration failed. Retry online with a push-enabled neXt build."
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
                status = "neXt couldn’t remove the local push setup."
                return
            }
            device.unregister()
            deviceToken = nil
            registeredThisLaunch = false
            lastUpload = nil
            status = "Off"
            return
        }
        current.revoking = true
        guard save(current) else {
            status = "neXt couldn’t save the request to turn alerts off."
            return
        }
        device.unregister()
        deviceToken = nil
        status = "Turn-off pending"
        retryAfter = .distantPast
        sync()
    }

    private func sync() {
        guard var current = enrollment, !busy, now() >= retryAfter,
              current.revoking || deviceToken != nil else { return }
        if !current.revoking, current.mayBeRegistered == false {
            // Persist this before the request so a crash cannot skip remote revocation.
            current.mayBeRegistered = true
            guard save(current) else {
                status = "neXt couldn’t save the provider registration state."
                retryAfter = now().addingTimeInterval(30)
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
                if self.enrollment != enrollment || self.senders != request.senders { sync() }
            }
            do {
                var upload = URLRequest(url: enrollment.provider.appendingPathComponent("v1").appendingPathComponent("subscription"))
                upload.httpMethod = "POST"
                upload.timeoutInterval = 12
                upload.setValue("application/json", forHTTPHeaderField: "Content-Type")
                upload.setValue("Bearer " + enrollment.secret, forHTTPHeaderField: "Authorization")
                upload.httpBody = try JSONEncoder().encode(request)
                guard try await uploader.upload(upload) == 204 else { throw URLError(.badServerResponse) }
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
                retryAfter = now().addingTimeInterval(30)
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

