import XCTest
@testable import SIMTrainingCore

final class CoreTests: XCTestCase {
    let json = #"{"id":17,"status":"planned","planned_at":"2027-02-16T22:00:00.000000Z","ends_at":"2027-02-17T04:00:00+00:00","schedule_timezone":"Europe/Ulyanovsk","venue":"FFS","is_extra":true,"extra_reason":"Practice","crew_id":9,"pilot":{"id":2,"name":"Pilot"},"instructor":{"id":3,"name":"Instructor"},"session":{"id":4,"title":"EXTRA","description":"Task"},"exercises":[{"id":10,"order":1,"name":"Approach","description":"Single engine","phase_of_flight":"Approach","duration_minutes":10,"min_score":3,"required_competencies":["pro"]}],"result":null}"#
    func detail() throws -> AssignmentDetail { try Wire.decoder().decode(AssignmentDetail.self, from: Data(json.utf8)) }
    func completeDraft(_ detail: AssignmentDetail) -> TrainingDraft {
        var draft = TrainingDraft(detail: detail)
        draft.exercises[10] = ExerciseDraft(score: 4, grades: ["pro": CompetencyGrade(score: 3, remarks: "  Check procedure  ")])
        draft.generalNotes = "  Practice completed  "
        return draft
    }
    func testServerDatesAndExtraAreDecodedWithoutDateShift() throws {
        let row = try detail()
        XCTAssertEqual(row.pilot.id, 2); XCTAssertEqual(row.isExtra, true)
        XCTAssertEqual(row.crewId, 9); XCTAssertEqual(row.exercises.first?.requiredCompetencies, ["pro"])
        let decoded = try Wire.decoder().decode(AssignmentDetail.self, from: Wire.encoder().encode(row))
        XCTAssertEqual(decoded, row)
        XCTAssertEqual(decoded.fingerprint, row.fingerprint)
    }
    func testSummaryGroupsByCrewAndUsesDeviceLocalDate() throws {
        let summary = #"{"id":17,"crew_id":9,"instructor_id":3,"session":{"id":4,"title":"EXTRA"},"pilot":{"id":2,"name":"Pilot"},"planned_at":"2027-02-16T22:00:00Z","ends_at":"2027-02-17T04:00:00Z","schedule_timezone":"Europe/Ulyanovsk","venue":"FFS","status":"planned","is_extra":true}"#
        let row = try Wire.decoder().decode(Assignment.self, from: Data(summary.utf8))
        XCTAssertEqual(row.localDay, "2027-02-17")
        XCTAssertTrue(row.timeText.contains("02:00")); XCTAssertEqual(row.groupKey, "crew:9")
    }
    func testIncompleteDraftCannotBecomeSubmission() throws {
        let row = try detail()
        XCTAssertThrowsError(try TrainingDraft(detail: row).payload(for: row))
        var draft = completeDraft(row); draft.exercises[10]?.score = 1
        XCTAssertThrowsError(try draft.payload(for: row))
    }
    func testSubmissionUsesAssignmentNotTemplateIdAndNormalizesRemarks() throws {
        let row = try detail(), draft = completeDraft(row)
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: draft.payload(for: row)) as? [String: Any])
        XCTAssertEqual(payload["session_id"] as? Int, 17)
        XCTAssertEqual(payload["pilot_id"] as? Int, 2)
        XCTAssertEqual(payload["general_notes"] as? String, "Practice completed")
        let exercises = try XCTUnwrap(payload["exercises"] as? [[String: Any]])
        XCTAssertEqual(exercises[0]["assignment_id"] as? Int, 10)
        XCTAssertEqual(exercises[0]["pro_remarks"] as? String, "Check procedure")
        XCTAssertNil(exercises[0]["wlm_score"])
    }
    func testChangedTimeOrExercisesStopsOfflineDraftSubmission() throws {
        let row = try detail(), draft = completeDraft(row)
        let moved = try Wire.decoder().decode(AssignmentDetail.self, from: Data(json.replacingOccurrences(of: "22:00:00.000000", with: "23:00:00.000000").utf8))
        XCTAssertNotEqual(row.fingerprint, moved.fingerprint)
        XCTAssertThrowsError(try draft.payload(for: moved))
        let changed = try Wire.decoder().decode(AssignmentDetail.self, from: Data(json.replacingOccurrences(of: "Single engine", with: "New task").utf8))
        XCTAssertThrowsError(try draft.payload(for: changed))
    }
    func testDraftCannotBeUsedForAnotherPilotOrInstructor() throws {
        let row = try detail(), draft = completeDraft(row)
        for (old, new) in [(#""id":2,"name":"Pilot""#, #""id":20,"name":"Pilot""#), (#""id":3,"name":"Instructor""#, #""id":30,"name":"Instructor""#)] {
            let changed = try Wire.decoder().decode(AssignmentDetail.self, from: Data(json.replacingOccurrences(of: old, with: new).utf8))
            XCTAssertThrowsError(try draft.payload(for: changed))
        }
    }
    func testPublishedResultIsMatchedBeforeUncertainDeliveryIsResolved() throws {
        let row = try detail(), draft = completeDraft(row)
        let grades = ["pro": CompetencyGrade(score: 3, remarks: "Check procedure")]
        let result = PublishedResult(id: 88, trainingId: 17, pilot: row.pilot, instructor: row.instructor, session: row.session,
            createdAt: Date(), generalNotes: "Practice completed", exercises: [ResultExercise(assignmentId: 10, exerciseName: "Approach", score: 4, grades: grades)])
        XCTAssertTrue(draft.matches(result, detail: row))
        var other = draft; other.generalNotes = "Different result"
        XCTAssertFalse(other.matches(result, detail: row))
        let roundtrip = try Wire.decoder().decode(PublishedResult.self, from: Wire.encoder().encode(result))
        XCTAssertEqual(roundtrip.exercises[0].grades["pro"]?.remarks, "Check procedure")
        XCTAssertTrue(draft.matches(roundtrip, detail: row))
    }
    func testDraftSurvivesRelaunchAndDoesNotLeakAcrossAccountsOrServers() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let a = try FileVault(root: root, server: "https://type-rating.survey-ebt.ru", userId: 1)
        var draft = completeDraft(try detail()); draft.delivery = .uncertain
        try a.save(draft: draft)
        let reopened = try FileVault(root: root, server: "https://type-rating.survey-ebt.ru", userId: 1)
        XCTAssertEqual(try reopened.drafts()[17]?.exercises[10]?.score, 4)
        XCTAssertEqual(try reopened.drafts()[17]?.delivery, .uncertain)
        let b = try FileVault(root: root, server: "https://type-rating.survey-ebt.ru", userId: 2)
        let c = try FileVault(root: root, server: "http://127.0.0.1:8002", userId: 1)
        XCTAssertTrue(try b.drafts().isEmpty); XCTAssertTrue(try c.drafts().isEmpty)
    }
    func testSnapshotRefreshNeverOverwritesDraftFile() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let files = try FileVault(root: root, server: "server", userId: 1)
        let row = try detail(); try files.save(draft: completeDraft(row))
        var snapshot = OfflineSnapshot(); snapshot.details[17] = row; snapshot.downloadedAt = Date()
        try files.save(snapshot: snapshot)
        XCTAssertEqual(try files.drafts()[17]?.generalNotes, "  Practice completed  ")
        XCTAssertEqual(try files.snapshot().details[17]?.pilot.id, 2)
    }
    func testUnreadableDraftIsNotSilentlyDeleted() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let files = try FileVault(root: root, server: "server", userId: 1)
        let file = files.directory.appendingPathComponent("draft-17.json")
        try Data("corrupted".utf8).write(to: file)
        XCTAssertThrowsError(try files.drafts())
        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path))
    }
    func testOnlyServerSelectedCompetenciesAreShownAndSubmitted() throws {
        let text = json.replacingOccurrences(of: #"["pro"]"#, with: #"["fpm","pro"]"#)
        let row = try Wire.decoder().decode(AssignmentDetail.self, from: Data(text.utf8))
        XCTAssertEqual(row.exercises[0].selectedCompetencies.map { $0.0 }, ["pro", "fpm"])
        var draft = completeDraft(row)
        draft.exercises[10]?.grades["fpm"] = CompetencyGrade(score: 4, remarks: "Manual flight")
        draft.exercises[10]?.grades["wlm"] = CompetencyGrade(score: 5, remarks: "Old hidden draft value")
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: draft.payload(for: row)) as? [String: Any])
        let exercise = try XCTUnwrap((payload["exercises"] as? [[String: Any]])?.first)
        XCTAssertEqual(exercise["pro_score"] as? Int, 3)
        XCTAssertEqual(exercise["fpm_score"] as? Int, 4)
        XCTAssertNil(exercise["wlm_score"]); XCTAssertNil(exercise["wlm_remarks"])
        XCTAssertEqual(draft.exercises[10]?.grades["wlm"]?.remarks, "Old hidden draft value")
    }
    func testEmptyServerSelectionDoesNotFallBackToAllCompetencies() throws {
        let text = json.replacingOccurrences(of: #"["pro"]"#, with: "[]")
        let row = try Wire.decoder().decode(AssignmentDetail.self, from: Data(text.utf8))
        XCTAssertTrue(row.exercises[0].selectedCompetencies.isEmpty)
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: completeDraft(row).payload(for: row)) as? [String: Any])
        let exercise = try XCTUnwrap((payload["exercises"] as? [[String: Any]])?.first)
        XCTAssertEqual(Set(exercise.keys), Set(["assignment_id", "score"]))
    }
    func testDeliveryVerificationUsesNeutralDefaultsForUnselectedCompetencies() throws {
        let row = try detail()
        var draft = completeDraft(row)
        draft.exercises[10]?.grades["wlm"] = CompetencyGrade(score: 5, remarks: "Do not submit")
        let result = PublishedResult(id: 1, trainingId: 17, pilot: row.pilot, instructor: row.instructor, session: row.session,
            createdAt: nil, generalNotes: "Practice completed", exercises: [ResultExercise(assignmentId: 10, exerciseName: "Approach", score: 4,
                grades: ["pro": CompetencyGrade(score: 3, remarks: "Check procedure"), "wlm": CompetencyGrade()])])
        XCTAssertTrue(draft.matches(result, detail: row))
        let other = PublishedResult(id: 1, trainingId: 17, pilot: row.pilot, instructor: row.instructor, session: row.session,
            createdAt: nil, generalNotes: "Practice completed", exercises: [ResultExercise(assignmentId: 10, exerciseName: "Approach", score: 4,
                grades: ["pro": CompetencyGrade(score: 3, remarks: "Check procedure"), "wlm": CompetencyGrade(score: 5, remarks: "Different server result")])])
        XCTAssertFalse(draft.matches(other, detail: row))
    }
    func testSelectedCompetenciesRemainAvailableInOfflineSnapshot() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let files = try FileVault(root: root, server: "server", userId: 1)
        var snapshot = OfflineSnapshot(); snapshot.details[17] = try detail()
        try files.save(snapshot: snapshot)
        let reopened = try files.snapshot()
        XCTAssertEqual(reopened.details[17]?.exercises[0].selectedCompetencies.map { $0.0 }, ["pro"])
    }
    func testUnsupportedServerCompetencyNeverSilentlyDisappearsOnSubmission() throws {
        let text = json.replacingOccurrences(of: #"["pro"]"#, with: #"["pro","new_code"]"#)
        let row = try Wire.decoder().decode(AssignmentDetail.self, from: Data(text.utf8))
        XCTAssertTrue(row.exercises[0].hasUnsupportedCompetencies)
        XCTAssertThrowsError(try completeDraft(row).payload(for: row))
    }

    func testDefiniteServerRejectionKeepsDraftRetryableButTimeoutDoesNot() {
        for status in [400,401,403,404,409,413,422,429] {
            XCTAssertEqual(PublicationStatus.afterFailure(HTTPFailure(status: status, message: "Rejected"), didSend: true), .draft)
        }
        for status in [408,499,500,502,503] {
            XCTAssertEqual(PublicationStatus.afterFailure(HTTPFailure(status: status, message: "Unknown"), didSend: true), .uncertain)
        }
        XCTAssertEqual(PublicationStatus.afterFailure(URLError(.timedOut), didSend: true), .uncertain)
        XCTAssertEqual(PublicationStatus.afterFailure(URLError(.timedOut), didSend: false), .draft)
    }
    func testValidationMessagesIdentifyRejectedExerciseWithoutHidingJSONErrors() {
        let data = Data(#"{"exercises":[{}, {"score":["This field is required."]}]}"#.utf8)
        XCTAssertEqual(HTTPFailure.responseMessage(data), "exercises[2].score: This field is required.")
        XCTAssertNil(HTTPFailure.responseMessage(Data("<html>proxy error</html>".utf8)))
    }
    func testOlderDraftWithoutSubmissionMessageRemainsReadable() throws {
        let row = try detail(); var draft = completeDraft(row)
        draft.lastSubmissionMessage = "HTTP 400"
        let bytes = try Wire.encoder().encode(draft)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String:Any])
        object.removeValue(forKey: "last_submission_message")
        let old = try Wire.decoder().decode(TrainingDraft.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertNil(old.lastSubmissionMessage)
        XCTAssertEqual(old.exercises[10]?.score,4)
    }

    func testPublicationReceiptMatchesDjangoResponseContract() throws {
        struct Receipt: Decodable { let ratingSessionId: Int }
        let response = Data(#"{"message":"Saved","rating_session_id":123,"exercises_saved":10}"#.utf8)
        XCTAssertEqual(try Wire.decoder().decode(Receipt.self, from: response).ratingSessionId,123)
    }

}
