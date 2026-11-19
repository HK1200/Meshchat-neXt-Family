import Foundation

struct FamilyAssets {
    static let scheme = "family"
    static let entryPoint = URL(string: "family://bundle/index.html")!

    let directory: URL

    func response(to request: URLRequest) throws -> (HTTPURLResponse, Data) {
        guard request.httpMethod == "GET", let url = request.url,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.scheme == Self.scheme, components.host == "bundle",
              components.user == nil, components.password == nil, components.port == nil,
              let asset = Self.asset(for: components.percentEncodedPath) else {
            throw URLError(.unsupportedURL)
        }

        let data = try Data(contentsOf: directory.appendingPathComponent(asset.path))
        let headers = [
            "Content-Type": asset.mime,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": """
                default-src 'none'; script-src 'self' 'unsafe-inline';                 style-src 'unsafe-inline'; img-src 'self' data:; media-src blob:;                 connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'
                """
        ]
        guard let response = HTTPURLResponse(
            url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers
        ) else {
            throw URLError(.badServerResponse)
        }
        return (response, data)
    }

    private static func asset(for path: String) -> (path: String, mime: String)? {
        switch path {
        case "/index.html":
            return ("index.html", "text/html; charset=utf-8")
        case "/jsQR.js", "/family-map.js":
            return (String(path.dropFirst()), "application/javascript; charset=utf-8")
        default:
            let parts = path.dropFirst().split(separator: "/", omittingEmptySubsequences: false)
            guard path.hasPrefix("/"), parts.count == 4,
                  parts[0] == "pnw-tiles" || parts[0] == "whatcom-tiles",
                  parts[3].hasSuffix(".png"),
                  [parts[1], parts[2], parts[3].dropLast(4)].allSatisfy({ part in
                      !part.isEmpty && part.utf8.allSatisfy { (48...57).contains($0) }
                  }) else {
                return nil
            }
            return (String(path.dropFirst()), "image/png")
        }
    }
}
