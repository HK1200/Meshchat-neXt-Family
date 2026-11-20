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
                     "blob:http://127.0.0.1:55444/owned-download"] {
            XCTAssertTrue(policy.allows(URL(string: path)), path)
        }
        for path in ["http://127.0.0.1:55445/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "https://127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://user@127.0.0.1:55444/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://example.invalid:55444/api/v1/lxmf-messages/attachment/\(hash)/file",
                     "http://127.0.0.1:55444/api/v1/config", "file:///etc/passwd", "data:text/plain,private",
                     "blob:http://example.invalid:55444/untrusted", "blob:http://127.0.0.1:55445/wrong-port"] {
            XCTAssertFalse(policy.allows(URL(string: path)), path)
        }
    }
}
