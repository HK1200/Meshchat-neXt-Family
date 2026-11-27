// SPDX-License-Identifier: 0BSD
import Darwin
import Foundation
import XCTest

final class IdentityRecoveryTests: XCTestCase {
    private let original = Data((0..<64).map(UInt8.init))
    private let replacement = Data((64..<128).map(UInt8.init))
    private func root() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("identity-recovery-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }
    private func identity(_ root: URL) -> URL {
        root.appendingPathComponent(NextIdentityRecovery.identityDirectoryName).appendingPathComponent("identity")
    }
    private func write(_ raw: Data, at root: URL) throws {
        try FileManager.default.createDirectory(at: identity(root).deletingLastPathComponent(), withIntermediateDirectories: true)
        try raw.write(to: identity(root))
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: identity(root).path)
    }
    private func pending(_ root: URL) -> URL { root.appendingPathComponent("identity-restore.pending") }
    private func mutatePending(_ root: URL, _ change: (inout [String: Any]) -> Void) throws {
        var value = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: pending(root))) as? [String: Any])
        change(&value)
        try JSONSerialization.data(withJSONObject: value).write(to: pending(root))
    }
    func testStandardReticulumKeyDerivesTheActualPythonIdentityAndMessagingAddress() throws {
        let key = try NextIdentityRecovery.Key(original)
        XCTAssertEqual(key.hash, "aca31af0441d81dbec71e82da0b4b5f5")
        XCTAssertEqual(key.messagingAddress, "fae321c442e3c9bdcd7a3e79d850e03c")
        XCTAssertEqual(key.bytes, original)
        for count in [0, 32, 63, 65, 4096] {
            XCTAssertThrowsError(try NextIdentityRecovery.Key(Data(repeating: 1, count: count)))
        }
    }
    func testStagingNeverChangesTheRunningIdentityHistoryOrPreferences() throws {
        let root = try self.root(); try write(original, at: root)
        let history = root.appendingPathComponent("messages-old.sqlite3"), preferences = root.appendingPathComponent("preferences.json")
        try Data("existing conversation and file".utf8).write(to: history)
        try Data("existing contacts and peers".utf8).write(to: preferences)
        XCTAssertTrue(try NextIdentityRecovery.stage(.init(replacement), support: root))
        let snapshot = try NextIdentityRecovery.status(support: root)
        XCTAssertEqual(snapshot.current?.bytes, original)
        XCTAssertEqual(snapshot.pending?.bytes, replacement)
        XCTAssertEqual(try Data(contentsOf: history), Data("existing conversation and file".utf8))
        XCTAssertEqual(try Data(contentsOf: preferences), Data("existing contacts and peers".utf8))
    }
    func testColdStartKeepsTheOldKeyAndConversationsAndCanSwitchBack() throws {
        let root = try self.root(); try write(original, at: root)
        let history = root.appendingPathComponent("messages-original.sqlite3")
        try Data("original private message history".utf8).write(to: history)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        try NextIdentityRecovery.applyPending(support: root)
        var snapshot = try NextIdentityRecovery.status(support: root)
        XCTAssertEqual(snapshot.current?.bytes, replacement)
        XCTAssertNil(snapshot.pending)
        XCTAssertEqual(snapshot.saved.map(\.bytes), [original])
        try NextIdentityRecovery.stage(XCTUnwrap(snapshot.saved.first), support: root)
        try NextIdentityRecovery.applyPending(support: root)
        snapshot = try NextIdentityRecovery.status(support: root)
        XCTAssertEqual(snapshot.current?.bytes, original)
        XCTAssertEqual(snapshot.saved.map(\.bytes), [replacement])
        XCTAssertEqual(try Data(contentsOf: history), Data("original private message history".utf8))
        let attributes = try FileManager.default.attributesOfItem(atPath: identity(root).path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
    }
    func testFreshInstallCanRestoreWithoutFirstGeneratingAnotherIdentity() throws {
        let root = try self.root()
        XCTAssertNil(try NextIdentityRecovery.status(support: root).current)
        try NextIdentityRecovery.stage(.init(original), support: root)
        XCTAssertFalse(FileManager.default.fileExists(atPath: identity(root).path))
        try NextIdentityRecovery.applyPending(support: root)
        XCTAssertEqual(try Data(contentsOf: identity(root)), original)
        XCTAssertNil(try NextIdentityRecovery.status(support: root).pending)
    }
    func testCancelAndAlreadyCurrentSelectionLeaveTheIdentityUnchanged() throws {
        let root = try self.root(); try write(original, at: root)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        try NextIdentityRecovery.cancel(support: root)
        try NextIdentityRecovery.applyPending(support: root)
        XCTAssertEqual(try Data(contentsOf: identity(root)), original)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        XCTAssertFalse(try NextIdentityRecovery.stage(.init(original), support: root))
        XCTAssertNil(try NextIdentityRecovery.status(support: root).pending)
        XCTAssertEqual(try Data(contentsOf: identity(root)), original)
    }
    func testAChangedCurrentIdentityCannotBeOverwrittenByAnOldRestore() throws {
        let root = try self.root(); try write(original, at: root)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        let newer = Data((128..<192).map(UInt8.init)); try write(newer, at: root)
        XCTAssertThrowsError(try NextIdentityRecovery.applyPending(support: root))
        XCTAssertEqual(try Data(contentsOf: identity(root)), newer)
        XCTAssertTrue(FileManager.default.fileExists(atPath: pending(root).path))
    }
    func testEveryMalformedPendingRecordPreservesTheOriginalKey() throws {
        let root = try self.root(); try write(original, at: root)
        let changes: [(inout [String: Any]) -> Void] = [
            { $0["version"] = 2 }, { $0["privateKey"] = "not a key" },
            { $0["replacementHash"] = String(repeating: "a", count: 32) },
            { $0["originalDigest"] = "invalid" }, { $0["path"] = "../../identity" },
            { $0["privateKey"] = Data(repeating: 1, count: 65).base64EncodedString() }
        ]
        for change in changes {
            try NextIdentityRecovery.stage(.init(replacement), support: root)
            try mutatePending(root, change)
            XCTAssertThrowsError(try NextIdentityRecovery.applyPending(support: root))
            XCTAssertEqual(try Data(contentsOf: identity(root)), original)
            try NextIdentityRecovery.cancel(support: root)
        }
    }
    func testAnInterruptedCompletedReplacementOnlyClearsItsPendingRecord() throws {
        let root = try self.root(); try write(original, at: root)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        let bytes = try Data(contentsOf: pending(root))
        try NextIdentityRecovery.applyPending(support: root)
        try bytes.write(to: pending(root)); try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: pending(root).path)
        try NextIdentityRecovery.applyPending(support: root)
        XCTAssertEqual(try Data(contentsOf: identity(root)), replacement)
        XCTAssertEqual(try NextIdentityRecovery.status(support: root).saved.map(\.bytes), [original])
        XCTAssertFalse(FileManager.default.fileExists(atPath: pending(root).path))
    }
    func testAnUnverifiableSavedCopyStopsReplacementBeforeTheLiveKeyChanges() throws {
        let root = try self.root(); try write(original, at: root)
        let backups = root.appendingPathComponent("identity-backups")
        try FileManager.default.createDirectory(at: backups, withIntermediateDirectories: false)
        let path = backups.appendingPathComponent(try NextIdentityRecovery.Key(original).hash + ".identity")
        try replacement.write(to: path); try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        XCTAssertThrowsError(try NextIdentityRecovery.applyPending(support: root))
        XCTAssertEqual(try Data(contentsOf: identity(root)), original)
        XCTAssertEqual(try Data(contentsOf: path), replacement)
    }
    func testSymlinkedStorageKeysAndBackupFoldersCannotEscapeTheApp() throws {
        let root = try self.root(), outside = try self.root(); try write(original, at: outside)
        let folder = identity(root).deletingLastPathComponent()
        try FileManager.default.createSymbolicLink(at: folder, withDestinationURL: identity(outside).deletingLastPathComponent())
        XCTAssertThrowsError(try NextIdentityRecovery.status(support: root))
        XCTAssertThrowsError(try NextIdentityRecovery.stage(.init(replacement), support: root))
        try FileManager.default.removeItem(at: folder)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        try FileManager.default.createSymbolicLink(at: identity(root), withDestinationURL: identity(outside))
        XCTAssertThrowsError(try NextIdentityRecovery.status(support: root))
        try FileManager.default.removeItem(at: identity(root)); try write(original, at: root)
        try NextIdentityRecovery.stage(.init(replacement), support: root)
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("identity-backups"), withDestinationURL: outside)
        XCTAssertThrowsError(try NextIdentityRecovery.applyPending(support: root))
        XCTAssertEqual(try Data(contentsOf: identity(root)), original)
        XCTAssertEqual(try Data(contentsOf: identity(outside)), original)
    }
    func testPublicStoredKeysAndSpecialFilesCannotEnterRecovery() throws {
        let root = try self.root(); try write(original, at: root)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: identity(root).path)
        XCTAssertThrowsError(try NextIdentityRecovery.status(support: root))
        XCTAssertNoThrow(try NextIdentityRecovery.importFile(identity(root)))
        try FileManager.default.removeItem(at: identity(root))
        XCTAssertEqual(mkfifo(identity(root).path, 0o600), 0)
        XCTAssertThrowsError(try NextIdentityRecovery.status(support: root))
        XCTAssertThrowsError(try NextIdentityRecovery.importFile(identity(root)))
    }
    func testImportedOversizedFilesAndSymlinksAreRejectedWithoutReadingUnboundedData() throws {
        let root = try self.root(), file = root.appendingPathComponent("identity.bin")
        try Data(repeating: 1, count: 1_000_000).write(to: file)
        XCTAssertThrowsError(try NextIdentityRecovery.importFile(file))
        try original.write(to: file)
        XCTAssertEqual(try NextIdentityRecovery.importFile(file).bytes, original)
        let link = root.appendingPathComponent("identity-link.bin")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: file)
        XCTAssertThrowsError(try NextIdentityRecovery.importFile(link))
    }
}
