import XCTest
@testable import FamilyLive

final class FamilyRoomServiceTests: XCTestCase {
    func testSavedRoomsDecodeBothServicesAndLegacyReticulum() throws {
        for service in [",\"service\":\"meshcore\"", ",\"service\":\"reticulum\"", ""] {
            let data = Data(("{\"id\":1,\"name\":\"Approved room\",\"key\":\"server\",\"channel\":\"general\",\"readOnly\":true" + service + "}").utf8)
            let room = try JSONDecoder().decode(FamilyRoom.self, from: data)
            XCTAssertEqual(room.service ?? "reticulum", service.contains("meshcore") ? "meshcore" : "reticulum")
            XCTAssertTrue(room.readOnly)
        }
    }
    func testRuntimePreservesCompanionByteLimit() throws {
        let runtime = try JSONDecoder().decode(FamilyRoomState.self, from: Data("{\"maxMessageBytes\":160,\"joined\":true,\"status\":\"Joined\",\"messages\":[]}".utf8))
        XCTAssertEqual(runtime.maxMessageBytes, 160)
        XCTAssertEqual(String(repeating: "é", count: 81).utf8.count, 162)
    }
}
