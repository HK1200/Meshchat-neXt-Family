import XCTest

final class AttachmentPolicyTests: XCTestCase {
    @MainActor
    func testOnlyOwnAttachmentAndBlobURLsCanDownload() throws {
        let base = try XCTUnwrap(URL(string: "http://127.0.0.1:55444/#/messages"))
        let policy = NextAttachmentDownloads(base: base, onComplete: { _ in XCTFail("No download expected") },
                                              onError: { _ in XCTFail("No download expected") })
        let hash = String(repeating: "a", count: 64)
        for path in ["http://127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/file?file_index=0",
                     "http://127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/image",
                     "http://127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/audio?raw=1",
                     "blob:http://127.0.0.1:55444/owned-download"] {
            XCTAssertTrue(policy.allows(URL(string: path)), path)
        }
        for path in ["http://127.0.0.1:55445/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://127.0.0.1:55445/api/v1/lxmf-messages/attachment/\(hash)/audio?raw=1",
                     "https://127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://user@127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://example.invalid:55444/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://127.0.0.1:55444/api/v1/config", "file:///etc/passwd", "data:text/plain,private",
                     "blob:http://example.invalid:55444/untrusted", "blob:http://127.0.0.1:55445/wrong-port"] {
            XCTAssertFalse(policy.allows(URL(string: path)), path)
        }
    }

    @MainActor
    func testMapExportsUseTheirOwnBoundWithoutIncreasingMessageAttachmentLimit() throws {
        let base = try XCTUnwrap(URL(string: "http://127.0.0.1:55444/"))
        let policy = NextAttachmentDownloads(base: base, onComplete: { _ in XCTFail() }, onError: { _ in XCTFail() })
        let map = "http://127.0.0.1:55444/api/v1/map/export/0123456789abcdef/download"
        XCTAssertEqual(policy.downloadLimit(for: URL(string: map)), 2 * 1024 * 1024 * 1024)
        XCTAssertEqual(policy.downloadLimit(for: URL(string: "http://127.0.0.1:55444/api/v1/lxmf-messages/attachment/" + String(repeating: "a", count: 64) + "/file")), 10_000_000)
        for invalid in [map.replacingOccurrences(of: "55444", with: "55445"), map + "/other", map.replacingOccurrences(of: "0123456789abcdef", with: "wrong"), map.replacingOccurrences(of: "127.0.0.1", with: "example.invalid")] {
            XCTAssertNil(policy.downloadLimit(for: URL(string: invalid)))
        }
    }

}
