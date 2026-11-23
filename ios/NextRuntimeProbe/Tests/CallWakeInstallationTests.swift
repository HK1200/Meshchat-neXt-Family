// SPDX-License-Identifier: 0BSD
import Darwin
import Foundation
import XCTest

final class CallWakeInstallationTests: XCTestCase {
    private let markerName = ".next-call-alert-installation-v1"
    private func directory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("call-install-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }
    func testColdReadDoesNotCreateConsentAndExplicitOptInRetainsTheMarker() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertNil(try NextCallWakeInstallation.read(support: root))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(markerName).path))
        let marker = try NextCallWakeInstallation.createForOptIn(support: root)
        XCTAssertEqual(marker.count, 32)
        XCTAssertEqual(try NextCallWakeInstallation.createForOptIn(support: root), marker)
        XCTAssertEqual(try NextCallWakeInstallation.read(support: root), marker)
    }
    func testAReplacementContainerCannotReuseThePreviousConsent() throws {
        let first = try directory(), second = try directory()
        defer { try? FileManager.default.removeItem(at: first); try? FileManager.default.removeItem(at: second) }
        XCTAssertNotEqual(try NextCallWakeInstallation.createForOptIn(support: first), try NextCallWakeInstallation.createForOptIn(support: second))
    }
    func testSymlinkMarkerNeverReadsOrChangesTheOutsideFile() throws {
        let root = try directory(), outside = try directory()
        defer { try? FileManager.default.removeItem(at: root); try? FileManager.default.removeItem(at: outside) }
        let marker = try NextCallWakeInstallation.createForOptIn(support: outside)
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent(markerName), withDestinationURL: outside.appendingPathComponent(markerName))
        XCTAssertThrowsError(try NextCallWakeInstallation.read(support: root))
        XCTAssertThrowsError(try NextCallWakeInstallation.createForOptIn(support: root))
        XCTAssertEqual(try NextCallWakeInstallation.read(support: outside), marker)
    }
    func testMalformedAndPubliclyReadableMarkersFailClosed() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let path = root.appendingPathComponent(markerName)
        try Data(repeating: 0, count: 31).write(to: path)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        XCTAssertThrowsError(try NextCallWakeInstallation.createForOptIn(support: root))
        try Data(repeating: 0, count: 32).write(to: path)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: path.path)
        XCTAssertThrowsError(try NextCallWakeInstallation.read(support: root))
    }
    func testNamedPipesFailWithoutWaitingForAnotherProcess() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertEqual(mkfifo(root.appendingPathComponent(markerName).path, 0o600), 0)
        XCTAssertThrowsError(try NextCallWakeInstallation.read(support: root))
        XCTAssertThrowsError(try NextCallWakeInstallation.createForOptIn(support: root))
    }
    func testRevocationRemovesOnlyItsMarkerAndNeverFollowsAnOutsideSymlink() throws {
        let root = try directory(), outside = try directory()
        defer { try? FileManager.default.removeItem(at: root); try? FileManager.default.removeItem(at: outside) }
        let original = try NextCallWakeInstallation.createForOptIn(support: outside)
        let identity = root.appendingPathComponent("identity")
        try Data(repeating: 42, count: 64).write(to: identity)
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent(markerName), withDestinationURL: outside.appendingPathComponent(markerName))
        try NextCallWakeInstallation.invalidate(support: root)
        XCTAssertNil(try NextCallWakeInstallation.read(support: root))
        XCTAssertEqual(try NextCallWakeInstallation.read(support: outside), original)
        XCTAssertEqual(try Data(contentsOf: identity), Data(repeating: 42, count: 64))
    }
    func testRevocationLeavesColdStartEmptyUntilAnotherExplicitOptIn() throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let original = try NextCallWakeInstallation.createForOptIn(support: root)
        try NextCallWakeInstallation.invalidate(support: root)
        XCTAssertNil(try NextCallWakeInstallation.read(support: root))
        XCTAssertNoThrow(try NextCallWakeInstallation.invalidate(support: root))
        XCTAssertNotEqual(try NextCallWakeInstallation.createForOptIn(support: root), original)
    }

}
