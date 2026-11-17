import Foundation

enum FamilyNativeHTTPS {
    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 4
        config.timeoutIntervalForResource = 4
        config.httpShouldSetCookies = false
        config.urlCredentialStorage = nil
        return URLSession(configuration: config, delegate: NoRedirects(), delegateQueue: nil)
    }()

    // This runs on the Python hint worker with the interpreter lock released.
    static func post(_ address: String, body: Data) -> Int32 {
        guard let url = URL(string: address), url.scheme == "https", url.host != nil else { return 400 }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let finished = DispatchSemaphore(value: 0)
        let result = Status()
        let task = session.dataTask(with: request) { _, response, error in
            if error == nil, let response = response as? HTTPURLResponse {
                result.store(Int32(response.statusCode))
            }
            finished.signal()
        }
        task.resume()
        guard finished.wait(timeout: .now() + 5) == .success else {
            task.cancel()
            return 503
        }
        return result.read()
    }

    private final class NoRedirects: NSObject, URLSessionTaskDelegate {
        func urlSession(
            _ session: URLSession, task: URLSessionTask,
            willPerformHTTPRedirection response: HTTPURLResponse,
            newRequest request: URLRequest,
            completionHandler: @escaping (URLRequest?) -> Void
        ) {
            completionHandler(nil)
        }
    }

    private final class Status: @unchecked Sendable {
        private let lock = NSLock()
        private var value: Int32 = 503

        func store(_ status: Int32) {
            lock.lock()
            value = status
            lock.unlock()
        }

        func read() -> Int32 {
            lock.lock()
            defer { lock.unlock() }
            return value
        }
    }
}
