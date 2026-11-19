import XCTest
@testable import FamilyLive

final class FamilyRoomParticipantTests: XCTestCase {
    func testRoomOnlyNamesDecodeWithoutChangingOriginalIdentity() throws {
        let data = Data("{\"seq\":1,\"text\":\"Private fixture\",\"nick\":\"Guardian label\",\"participantId\":\"abababab\",\"reportedName\":\"Reported name\",\"savedName\":\"Guardian label\"}".utf8)
        let row = try JSONDecoder().decode(FamilyRoomMessage.self, from: data)
        XCTAssertEqual(row.participantId, "abababab")
        XCTAssertEqual(row.reportedName, "Reported name")
        XCTAssertEqual(row.savedName, "Guardian label")
        XCTAssertEqual(row.nick, "Guardian label")
        let legacy = try JSONDecoder().decode(FamilyRoomMessage.self, from: Data("{\"seq\":2,\"text\":\"Older message\"}".utf8))
        XCTAssertNil(legacy.participantId)
        XCTAssertNil(legacy.savedName)
    }
}
