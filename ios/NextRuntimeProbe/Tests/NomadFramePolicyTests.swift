// SPDX-License-Identifier: 0BSD
import Foundation
import XCTest

final class NomadFramePolicyTests: XCTestCase {
    private let base = URL(string: "http://127.0.0.1:55444/#/messages")!
    func testBundledOpaqueRendererAcceptsOnlyItsOwnSessionAndCacheBusters() {
        for suffix in ["", "?v=2026-11-21T12%3A00%3A00Z", "?t=1790000000", "?v=build%3Ft%3D1790000000"] {
            XCTAssertTrue(NextNomadFramePolicy.allows(URL(string: "http://127.0.0.1:55444/nomad-crash-tab.html" + suffix), base: base), suffix)
        }
    }
    func testRendererRuleCannotOpenPrivateApiOtherFramesPortsOrOrigins() {
        for url in ["http://127.0.0.1:55444/api/v1/config", "http://127.0.0.1:55444/index.html",
                    "http://127.0.0.1:55445/nomad-crash-tab.html", "https://127.0.0.1:55444/nomad-crash-tab.html",
                    "http://example.invalid:55444/nomad-crash-tab.html", "http://user@127.0.0.1:55444/nomad-crash-tab.html",
                    "http://127.0.0.1:55444/nomad-crash-tab.html?token=secret", "http://127.0.0.1:55444/nomad-crash-tab.html?t=no",
                    "http://127.0.0.1:55444/nomad-crash-tab.html?v=one&v=two", "http://127.0.0.1:55444/nomad-crash-tab.html#api",
                    "about:blank", "blob:http://127.0.0.1:55444/nomad-renderer", "file:///nomad-crash-tab.html"] {
            XCTAssertFalse(NextNomadFramePolicy.allows(URL(string: url), base: base), url)
        }
        XCTAssertFalse(NextNomadFramePolicy.allows(nil, base: base))
    }
}
