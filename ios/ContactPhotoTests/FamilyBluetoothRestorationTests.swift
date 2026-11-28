import XCTest
@testable import FamilyLive

final class FamilyBluetoothRestorationTests: XCTestCase {
    func testOnlyOurSystemRestorationIdentifierCanStartColdRadioHandling() {
        XCTAssertFalse(FamilyBluetoothRestoration.shouldRestore(nil))
        XCTAssertFalse(FamilyBluetoothRestoration.shouldRestore([]))
        XCTAssertFalse(FamilyBluetoothRestoration.shouldRestore(["other.central"]))
        XCTAssertTrue(FamilyBluetoothRestoration.shouldRestore(["other.central", FamilyBluetoothRestoration.identifier]))
    }
    func testUnrestoredBytesCannotCreateAnApprovedSession() {
        var state = FamilyBluetoothRestoration()
        let id = UUID(); state.receive(Data([1, 2]), from: id)
        XCTAssertFalse(state.contains(id)); XCTAssertNil(state.admit(id))
    }
    func testSavedProfileAdoptionReturnsOrderedBytesOnlyOnce() throws {
        var state = FamilyBluetoothRestoration(); let id = UUID()
        XCTAssertNotNil(state.remember(id))
        state.receive(Data([1, 2]), from: id); state.receive(Data([3]), from: id)
        let pending = try XCTUnwrap(state.admit(id))
        XCTAssertEqual(pending.packets, [Data([1, 2]), Data([3])]); XCTAssertEqual(pending.bytes, 3)
        XCTAssertFalse(pending.overflowed); XCTAssertNil(state.admit(id))
        state.receive(Data([4]), from: id); XCTAssertNil(state.admit(id))
    }
    func testByteOverflowFailsTheWholeStreamWithoutReturningTruncatedPackets() throws {
        var state = FamilyBluetoothRestoration(); let id = UUID()
        _ = state.remember(id)
        state.receive(Data(repeating: 1, count: FamilyBluetoothRestoration.maximumBytes), from: id)
        state.receive(Data([2]), from: id); state.receive(Data([3]), from: id)
        let pending = try XCTUnwrap(state.admit(id))
        XCTAssertTrue(pending.overflowed); XCTAssertTrue(pending.packets.isEmpty); XCTAssertEqual(pending.bytes, 0)
    }
    func testPacketCountIsBoundedEvenForTinyNotifications() throws {
        var state = FamilyBluetoothRestoration(); let id = UUID()
        _ = state.remember(id)
        for _ in 0...FamilyBluetoothRestoration.maximumPackets { state.receive(Data([1]), from: id) }
        let pending = try XCTUnwrap(state.admit(id))
        XCTAssertTrue(pending.overflowed); XCTAssertTrue(pending.packets.isEmpty)
    }
    func testDisabledUnadoptedRadiosExpireAndCannotDeliverData() throws {
        var state = FamilyBluetoothRestoration(); let id = UUID()
        let lease = try XCTUnwrap(state.remember(id)); state.receive(Data([1]), from: id)
        XCTAssertTrue(state.expire(id, generation: lease))
        XCTAssertFalse(state.expire(id, generation: lease)); XCTAssertNil(state.admit(id))
    }
    func testOldDeadlineCannotCancelAnAdoptedOrReplacementRadio() throws {
        var state = FamilyBluetoothRestoration(); let id = UUID()
        let old = try XCTUnwrap(state.remember(id)); _ = state.admit(id)
        XCTAssertFalse(state.expire(id, generation: old))
        let replacement = try XCTUnwrap(state.remember(id)); XCTAssertNotEqual(old, replacement)
        XCTAssertFalse(state.expire(id, generation: old)); XCTAssertTrue(state.contains(id))
        XCTAssertTrue(state.expire(id, generation: replacement))
    }
    func testExplicitCloseRevokesQueuedBytesAndDoesNotAffectOtherRadios() throws {
        var state = FamilyBluetoothRestoration(); let first = UUID(), second = UUID()
        _ = state.remember(first); _ = state.remember(second)
        state.receive(Data([1]), from: first); state.receive(Data([2]), from: second)
        XCTAssertTrue(state.remove(first)); XCTAssertFalse(state.remove(first))
        XCTAssertNil(state.admit(first)); XCTAssertEqual(try XCTUnwrap(state.admit(second)).packets, [Data([2])])
    }
    func testRestoredDeviceCountAndDuplicateEntriesAreBounded() throws {
        var state = FamilyBluetoothRestoration(); let first = UUID()
        _ = state.remember(first); XCTAssertNil(state.remember(first))
        for _ in 1..<FamilyBluetoothRestoration.maximumRadios { XCTAssertNotNil(state.remember(UUID())) }
        XCTAssertNil(state.remember(UUID()))
        XCTAssertNotNil(state.admit(first)); XCTAssertNotNil(state.remember(UUID()))
    }
}
