import Foundation
import SwiftUI
import UIKit
import Darwin

struct NextTCPPeer: Codable, Identifiable, Equatable {
    var id: String
    var host: String
    var port: Int
    var enabled: Bool
    var online: Bool? = nil
    var status: String? = nil

    static func initial(host: String, port: Int) -> [Self] {
        let defaults: [(String, Int)] = [("rmap.world", 4343), ("rmap.world", 4242),
            ("reticulum.washmesh.net", 7242), ("rns.chimesh.org", 4242)]
        let normalized = canonicalHost(host)
        let useDefaults = normalized == "rmap.world" && [4242, 4343].contains(port)
        let endpoints = useDefaults ? defaults : [(normalized, port)] + defaults.filter { $0.0 != normalized || $0.1 != port }
        return endpoints.enumerated().map {
            Self(id: "peer-\($0.offset)", host: $0.element.0, port: $0.element.1,
                 enabled: useDefaults || $0.offset == 0)
        }
    }

    static func canonicalHost(_ value: String) -> String {
        var host = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        while host.hasSuffix(".") { host.removeLast() }
        return host
    }

    static func encodeSettings(_ peers: [Self]) throws -> String {
        let saved = peers.map { peer in
            Self(id: peer.id, host: peer.host, port: peer.port, enabled: peer.enabled)
        }
        return String(decoding: try JSONEncoder().encode(saved), as: UTF8.self)
    }
}

private struct NextTCPDraft: Identifiable, Equatable {
    let id: String
    var host: String
    var port: String
    var enabled: Bool

    init(_ peer: NextTCPPeer) {
        id = peer.id; host = peer.host; port = String(peer.port); enabled = peer.enabled
    }

    func value() throws -> NextTCPPeer {
        let host = NextTCPPeer.canonicalHost(host)
        var ipv6 = in6_addr()
        let isIPv6 = host.withCString { inet_pton(AF_INET6, $0, &ipv6) == 1 }
        let domain = !host.isEmpty && host.count <= 253 && host.split(separator: ".", omittingEmptySubsequences: false)
            .allSatisfy { $0.range(of: "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", options: .regularExpression) != nil }
        guard domain || isIPv6, let port = Int(port), (1...65535).contains(port) else {
            throw NSError(domain: "neXt", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "Enter a hostname or IP address and a port from 1 to 65535. Do not include a URL or a port in the hostname."])
        }
        return NextTCPPeer(id: id, host: host, port: port, enabled: enabled)
    }
}

private enum NextTCPAPI {
    struct Reply: Decodable { let peers: [NextTCPPeer] }
    struct Token: Decodable { let csrf_token: String }
    struct Failure: Decodable { let message: String }
    struct Update: Encodable { let peers: [NextTCPPeer] }

    static func load(_ base: URL) async throws -> [NextTCPPeer] {
        let endpoint = URL(string: "/api/v1/preview/reticulum-connections", relativeTo: base)!
        let (data, response) = try await URLSession.shared.data(from: endpoint)
        try check(data, response)
        return try JSONDecoder().decode(Reply.self, from: data).peers
    }

    static func save(_ peers: [NextTCPPeer], at base: URL) async throws -> [NextTCPPeer] {
        let (data, response) = try await URLSession.shared.data(from: URL(string: "/api/v1/auth/csrf", relativeTo: base)!)
        try check(data, response)
        let token = try JSONDecoder().decode(Token.self, from: data).csrf_token
        var request = URLRequest(url: URL(string: "/api/v1/preview/reticulum-connections", relativeTo: base)!)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(token, forHTTPHeaderField: "X-CSRF-Token")
        request.setValue("http://127.0.0.1:\(base.port!)", forHTTPHeaderField: "Origin")
        request.httpBody = try JSONEncoder().encode(Update(peers: peers))
        let (result, savedResponse) = try await URLSession.shared.data(for: request)
        try check(result, savedResponse)
        return try JSONDecoder().decode(Reply.self, from: result).peers
    }

    private static func check(_ data: Data, _ response: URLResponse) throws {
        guard let status = (response as? HTTPURLResponse)?.statusCode, (200..<300).contains(status) else {
            let message = (try? JSONDecoder().decode(Failure.self, from: data).message) ?? "Could not reach neXt’s local connection service."
            throw NSError(domain: "neXt", code: 2, userInfo: [NSLocalizedDescriptionKey: message])
        }
    }
}

struct NextTCPConnections: View {
    let base: URL?
    let initial: [NextTCPPeer]
    let onSaved: ([NextTCPPeer]) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var drafts: [NextTCPDraft] = []
    @State private var statuses: [NextTCPPeer] = []
    @State private var lastSaved: [NextTCPDraft]?
    @State private var error = ""
    @State private var statusUnavailable = false
    @State private var busy = false
    @State private var loaded = false
    @State private var scrollTarget: String?
    private enum Field: Hashable { case host(String), port(String) }
    @FocusState private var focusedField: Field?

    var body: some View {
        NavigationStack {
            ScrollViewReader { reader in
                Form {
                    Section {
                        Text("Each enabled peer connects independently. Turn off services you don’t use, edit a peer, or add another hostname and port.")
                    }
                    ForEach($drafts) { $draft in
                        Section {
                            Toggle("Enabled", isOn: $draft.enabled)
                                .accessibilityIdentifier("tcp-peer-enabled-\(draft.id)")
                            TextField("Hostname or IP address", text: $draft.host)
                                .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                                .focused($focusedField, equals: .host(draft.id))
                                .accessibilityIdentifier("tcp-peer-host-\(draft.id)")
                            TextField("Port", text: $draft.port).keyboardType(.numberPad)
                                .focused($focusedField, equals: .port(draft.id))
                                .accessibilityIdentifier("tcp-peer-port-\(draft.id)")
                            Text(status(for: draft)).foregroundStyle(.secondary)
                                .accessibilityIdentifier("tcp-peer-status-\(draft.id)")
                            Button("Remove peer", role: .destructive) { drafts.removeAll { $0.id == draft.id } }
                        }.id(draft.id)
                    }
                    Section {
                        Button("Add TCP peer", systemImage: "plus") {
                            let peer = NextTCPPeer(id: UUID().uuidString, host: "", port: 4343, enabled: false)
                            drafts.append(NextTCPDraft(peer))
                            scrollTarget = peer.id
                        }.accessibilityIdentifier("add-tcp-peer").disabled(drafts.count >= 32)
                        if lastSaved == drafts {
                            Text("Connections saved").accessibilityIdentifier("tcp-peers-saved")
                        }
                        if !error.isEmpty { Text(error).foregroundStyle(.red) }
                    }
                }
                .onChange(of: scrollTarget) { _, target in
                    if let target { withAnimation { reader.scrollTo(target, anchor: .top) } }
                }
                .accessibilityIdentifier("next-tcp-form")
                .disabled(busy || !loaded)
                .scrollDismissesKeyboard(.interactively)
                .navigationTitle("TCP connections")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Save") { Task { await save() } }
                            .disabled(busy || !loaded).accessibilityIdentifier("save-tcp-peers")
                    }
                    ToolbarItemGroup(placement: .keyboard) {
                        Spacer()
                        Button("Done typing") { focusedField = nil }
                    }
                }
                .task {
                    guard let base else {
                        drafts = initial.map(NextTCPDraft.init)
                        loaded = true
                        return
                    }
                    while !Task.isCancelled {
                        do {
                            let fresh = try await NextTCPAPI.load(base)
                            if Task.isCancelled { return }
                            statuses = fresh
                            if !loaded {
                                drafts = fresh.map(NextTCPDraft.init)
                                loaded = true
                                error = ""
                            }
                            statusUnavailable = false
                        } catch {
                            if Task.isCancelled { return }
                            statusUnavailable = true
                            if !loaded { self.error = error.localizedDescription }
                        }
                        do { try await Task.sleep(for: .seconds(3)) }
                        catch { return }
                    }
                }
            }
        }
    }

    private func status(for draft: NextTCPDraft) -> String {
        guard let value = try? draft.value() else { return "Enter a hostname and port" }
        if let saved = statuses.first(where: { $0.id == value.id }) {
            guard saved.host == value.host, saved.port == value.port, saved.enabled == value.enabled else { return "Unsaved changes" }
            return statusUnavailable ? "Status unavailable" : saved.status ?? "Offline"
        }
        return base == nil ? (value.enabled ? "Connects when neXt starts" : "Disabled") : "Not saved yet"
    }

    private func save() async {
        focusedField = nil
        busy = true
        defer { busy = false }
        do {
            var peers = try drafts.map { try $0.value() }
            let keys = peers.map { "\($0.host):\($0.port)" }
            guard Set(keys).count == keys.count else {
                throw NSError(domain: "neXt", code: 3, userInfo: [NSLocalizedDescriptionKey: "That hostname and port are already listed."])
            }
            if let base { peers = try await NextTCPAPI.save(peers, at: base) }
            onSaved(peers)
            statuses = peers
            drafts = peers.map(NextTCPDraft.init)
            lastSaved = drafts
            error = ""
        } catch { self.error = error.localizedDescription }
    }
}
