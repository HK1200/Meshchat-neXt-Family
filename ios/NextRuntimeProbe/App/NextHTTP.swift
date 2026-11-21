import Foundation

/// Only this app's verified loopback process receives the private session header.
final class NextHTTP {
    static let shared = NextHTTP()
    private struct Info: Decodable {
        let version: Int
        let pid: Int32
        let origin: String
        let instance: String
        let capability: String
    }
    private final class Access: @unchecked Sendable {
        private let lock = NSLock()
        private var value: (origin: URL, capability: String)?
        func clear() { lock.lock(); value = nil; lock.unlock() }
        func configure(origin: URL, capability: String) {
            lock.lock(); value = (origin, capability); lock.unlock()
        }
        func authorize(_ request: URLRequest) throws -> URLRequest {
            lock.lock(); let current = value; lock.unlock()
            guard let current, let url = request.url,
                  url.scheme == "http", url.host == "127.0.0.1",
                  url.user == nil, url.password == nil, url.port == current.origin.port else {
                throw URLError(.userAuthenticationRequired)
            }
            var result = request
            result.setValue(current.capability, forHTTPHeaderField: "X-neXt-Session")
            result.httpShouldHandleCookies = false
            result.cachePolicy = .reloadIgnoringLocalCacheData
            return result
        }
    }
    private final class Redirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
        let access: Access
        init(_ access: Access) { self.access = access }
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                        completionHandler: @escaping (URLRequest?) -> Void) {
            // Never forward a session header to a different host or local port.
            completionHandler(try? access.authorize(request))
        }
    }
    private let access: Access
    private let session: URLSession
    init() {
        let access = Access()
        self.access = access
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 30
        session = URLSession(configuration: configuration, delegate: Redirects(access), delegateQueue: nil)
    }
    deinit { session.invalidateAndCancel() }

    func configure(_ data: Data, for url: URL) throws {
        access.clear()
        guard data.count <= 16384 else { throw URLError(.userAuthenticationRequired) }
        let info = try JSONDecoder().decode(Info.self, from: data)
        guard info.version == 1, info.pid == ProcessInfo.processInfo.processIdentifier,
              let origin = URL(string: info.origin), origin.scheme == "http", origin.host == "127.0.0.1",
              origin.user == nil, origin.password == nil, origin.path.isEmpty,
              origin.query == nil, origin.fragment == nil, let port = origin.port, (1...65535).contains(port),
              url.scheme == origin.scheme, url.host == origin.host, url.port == port,
              info.capability.utf8.count == 43,
              info.capability.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil,
              info.instance.utf8.count == 32,
              info.instance.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else {
            throw URLError(.userAuthenticationRequired)
        }
        access.configure(origin: origin, capability: info.capability)
    }
    func authorized(_ request: URLRequest) throws -> URLRequest { try access.authorize(request) }
    func webRequest(for url: URL) throws -> URLRequest {
        var request = try access.authorize(URLRequest(url: url))
        // WKWebView must accept the authenticated root response's HttpOnly
        // cookie before its own fetches and WebSocket can use the session.
        request.httpShouldHandleCookies = true
        return request
    }
    func data(from url: URL) async throws -> (Data, URLResponse) { try await data(for: URLRequest(url: url)) }
    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await session.data(for: access.authorize(request))
    }
}
