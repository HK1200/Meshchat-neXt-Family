// SPDX-License-Identifier: 0BSD
import Darwin
import Foundation

/// One runtime owner for the visible app and future incoming-call wakeups.
/// No PushKit registration, permission request or background lease occurs here.
@MainActor
enum NextRuntimeLauncher {
    static let shared = NextRuntimeStartup(start: NextRuntimeBoot.start)
}

@MainActor
private enum NextRuntimeBoot {
    static func start(configuration: Data?) async throws -> NextRuntimeSession {
        guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        let modules = resources.appendingPathComponent("staged")
        let directory = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask, appropriateFor: nil, create: true
        )
        let ready = directory.appendingPathComponent("next-\(UUID().uuidString).url")
        let config = ready.deletingPathExtension().appendingPathExtension("json")
        let address = ready.deletingPathExtension().appendingPathExtension("address")
        let error = ready.deletingPathExtension().appendingPathExtension("error")
        if let configuration {
            try configuration.write(to: config, options: .atomic)
        }
        let home = resources.appendingPathComponent("python").path
        let modulePath = modules.path
        let readyPath = ready.path
        next_probe_set_https_post { url, body, length in
            guard let url, let body else { return 400 }
            return FamilyNativeHTTPS.post(String(cString: url), body: Data(bytes: body, count: length))
        }
        next_probe_set_credentials { request in
            guard let request else { return nil }
            return strdup(NextCredentials.shared.request(String(cString: request)))
        }
        next_probe_set_sip { request in
            guard let request else { return nil }
            return strdup(NextSIPBridge.request(String(cString: request)))
        }
        next_probe_set_location { request in
            guard let request else { return nil }
            return strdup(NextLocationBridge.request(String(cString: request)))
        }
        next_probe_set_voice { request in
            guard let request else { return nil }
            return strdup(NextReticulumBridge.request(String(cString: request)))
        }
        next_probe_set_bluetooth { request in
            guard let request else { return nil }
            return strdup(FamilyBluetooth.shared.request(String(cString: request)))
        }
        DispatchQueue.global(qos: .userInitiated).async {
            next_probe_run(home, modulePath, readyPath)
        }
        defer {
            for file in [ready, config, address, error] {
                try? FileManager.default.removeItem(at: file)
            }
        }
        for _ in 0..<600 {
            if let problem = try? String(contentsOf: error, encoding: .utf8) {
                throw NSError(domain: "neXt", code: 1, userInfo: [NSLocalizedDescriptionKey: problem])
            }
            if let value = try? String(contentsOf: ready, encoding: .utf8),
               let url = URL(string: value), url.scheme == "http", url.host == "127.0.0.1", url.port != nil {
                let accessFile = directory.appendingPathComponent("next-runtime-info.json")
                try NextHTTP.shared.configure(Data(contentsOf: accessFile), for: url)
                return NextRuntimeSession(url: url, address: try? String(contentsOf: address, encoding: .utf8))
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw URLError(.timedOut)
    }
}
