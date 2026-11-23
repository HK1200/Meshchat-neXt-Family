// SPDX-License-Identifier: 0BSD
import Foundation

/// Short, bounded, non-redirecting provider lookup for an already admitted call.
@MainActor final class NextCallWakeQuery {
    private let session: URLSession
    init() {
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false; config.httpCookieStorage = nil
        config.urlCredentialStorage = nil; config.urlCache = nil
        config.timeoutIntervalForRequest = 3; config.timeoutIntervalForResource = 4
        session = URLSession(configuration: config, delegate: NoRedirect(), delegateQueue: nil)
    }
    deinit { session.invalidateAndCancel() }
    func response(_ request: URLRequest) async throws -> Data? {
        guard let url = request.url, url.scheme == "https", url.host != nil,
              url.user == nil, url.password == nil else { throw URLError(.badURL) }
        let (stream, response) = try await session.bytes(for: request)
        defer { stream.task.cancel() }
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              response.expectedContentLength <= 2304 else { return nil }
        var data = Data()
        for try await byte in stream {
            try Task.checkCancellation()
            guard data.count < 2304 else { throw URLError(.dataLengthExceedsMaximum) }
            data.append(byte)
        }
        return data
    }
    private final class NoRedirect: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                        completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    }
}
