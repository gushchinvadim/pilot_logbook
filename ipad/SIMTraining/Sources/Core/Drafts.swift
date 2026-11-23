import Foundation

struct ExerciseDraft: Codable, Equatable {
    var score: Int?
    var grades: [String: CompetencyGrade] = [:]
}
enum DraftDelivery: String, Codable { case draft, uncertain, published }
struct TrainingDraft: Codable, Identifiable {
    let id: Int
    let pilotId: Int
    let instructorId: Int
    let fingerprint: String
    var exercises: [Int: ExerciseDraft] = [:]
    var generalNotes: String = ""
    var updatedAt: Date = Date()
    var delivery: DraftDelivery = .draft
    var lastSubmissionMessage: String?
    var publishedResultId: Int?
    init(detail: AssignmentDetail) {
        id = detail.id; pilotId = detail.pilot.id; instructorId = detail.instructor.id; fingerprint = detail.fingerprint
    }
    var completedCount: Int { exercises.values.filter { (2...5).contains($0.score ?? 0) }.count }
    func payload(for detail: AssignmentDetail) throws -> Data {
        guard id == detail.id, pilotId == detail.pilot.id, instructorId == detail.instructor.id,
              fingerprint == detail.fingerprint else { throw DraftError.changedAssignment }
        guard !detail.exercises.isEmpty, detail.exercises.allSatisfy({ (2...5).contains(exercises[$0.id]?.score ?? 0) }) else {
            throw DraftError.incomplete
        }
        guard !detail.exercises.contains(where: { $0.hasUnsupportedCompetencies }) else { throw DraftError.unsupportedCompetencies }
        let rows: [[String: Any]] = detail.exercises.map { exercise in
            let draft = exercises[exercise.id]!
            var row: [String: Any] = ["assignment_id": exercise.id, "score": draft.score!]
            for (key, _) in exercise.selectedCompetencies {
                let grade = draft.grades[key] ?? CompetencyGrade()
                row[key + "_score"] = grade.score
                row[key + "_remarks"] = grade.remarks.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            return row
        }
        return try JSONSerialization.data(withJSONObject: ["pilot_id": pilotId, "session_id": id,
            "general_notes": generalNotes.trimmingCharacters(in: .whitespacesAndNewlines), "exercises": rows], options: [.sortedKeys])
    }
    func matches(_ result: PublishedResult, detail: AssignmentDetail) -> Bool {
        guard result.trainingId == id, result.pilot.id == pilotId, result.instructor.id == instructorId, result.session.id == detail.session.id,
              result.generalNotes == generalNotes.trimmingCharacters(in: .whitespacesAndNewlines),
              result.exercises.count == detail.exercises.count,
              Set(result.exercises.map(\.assignmentId)) == Set(detail.exercises.map(\.id)) else { return false }
        for item in result.exercises {
            guard let draft = exercises[item.assignmentId], draft.score == item.score,
                  let exercise = detail.exercises.first(where: { $0.id == item.assignmentId }), !exercise.hasUnsupportedCompetencies else { return false }
            for (key, _) in Competencies.all {
                // Omitted server fields have score 0 and empty remarks. Keep legacy draft values locally, but never submit them.
                let a = exercise.requiredCompetencies.contains(key) ? (draft.grades[key] ?? CompetencyGrade()) : CompetencyGrade()
                let b = item.grades[key] ?? CompetencyGrade()
                if a.score != b.score || a.remarks.trimmingCharacters(in: .whitespacesAndNewlines) != b.remarks { return false }
            }
        }
        return true
    }
}
enum DraftError: LocalizedError {
    case incomplete, changedAssignment, unsupportedCompetencies
    var errorDescription: String? {
        switch self {
        case .unsupportedCompetencies: return "В задании есть новые компетенции. Обновите приложение перед отправкой результата."
        case .incomplete: return "Заполните общую оценку каждого упражнения."
        case .changedAssignment: return "Задание или расписание изменилось. Черновик сохранён. Сверьте актуальное назначение с ответственным перед отправкой."
        }
    }
}
