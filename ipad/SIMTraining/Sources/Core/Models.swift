import Foundation
import CryptoKit

enum Wire {
    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { value in
            let text = try value.singleValueContainer().decode(String.self)
            for fractional in [true, false] {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = fractional ? [.withInternetDateTime, .withFractionalSeconds] : [.withInternetDateTime]
                if let date = formatter.date(from: text) { return date }
            }
            throw DecodingError.dataCorrupted(.init(codingPath: value.codingPath, debugDescription: "Invalid server date"))
        }
        return decoder
    }
    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
    static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
}

struct Profile: Codable, Equatable {
    let id: Int
    let username: String
    let name: String
    let roles: [String]
    let instructorId: Int?
    let pilotId: Int?
    var isInstructor: Bool { roles.contains("instructor") && instructorId != nil }
}
struct Person: Codable, Equatable, Identifiable { let id: Int; let name: String }
struct TrainingTemplate: Codable, Equatable, Identifiable {
    let id: Int
    let title: String
    var description: String?
}
struct Assignment: Codable, Equatable, Identifiable {
    let id: Int
    let crewId: Int?
    let instructorId: Int
    let session: TrainingTemplate
    let pilot: Person
    var plannedAt: Date?
    var endsAt: Date?
    let scheduleTimezone: String?
    let venue: String?
    var status: String
    let isExtra: Bool?
    var groupKey: String { crewId.map { "crew:\($0)" } ?? "single:\(id)" }
    var zone: TimeZone { TimeZone(identifier: scheduleTimezone ?? "UTC") ?? TimeZone(secondsFromGMT: 0)! }
    var statusText: String { ["planned":"Запланирована", "completed":"Проведена", "cancelled":"Отменена"][status] ?? status }
    var timeText: String {
        guard let plannedAt else { return "Время не назначено" }
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "ru_RU"); formatter.timeZone = zone
        formatter.dateFormat = "dd MMM yyyy · HH:mm"
        let start = formatter.string(from: plannedAt)
        formatter.dateFormat = "HH:mm"
        let end = endsAt.map { " — " + formatter.string(from: $0) } ?? ""
        return start + end + " · " + zone.identifier
    }
    var localDay: String {
        guard let plannedAt else { return "" }
        let formatter = DateFormatter(); formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.timeZone = zone; formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: plannedAt)
    }
}
struct Exercise: Codable, Equatable, Identifiable {
    let id: Int
    let order: Int?
    let name: String
    let description: String
    let phaseOfFlight: String
    let durationMinutes: Int?
    let minScore: Int
    let requiredCompetencies: [String]
    var selectedCompetencies: [(String, String)] {
        Competencies.all.filter { requiredCompetencies.contains($0.0) }
    }
    var hasUnsupportedCompetencies: Bool {
        !Set(requiredCompetencies).isSubset(of: Set(Competencies.all.map { $0.0 }))
    }
}
struct AssignmentDetail: Codable, Equatable, Identifiable {
    let id: Int
    let status: String
    let plannedAt: Date?
    let endsAt: Date?
    let scheduleTimezone: String?
    let venue: String?
    let isExtra: Bool?
    let extraReason: String?
    let crewId: Int?
    let pilot: Person
    let instructor: Person
    let session: TrainingTemplate
    let exercises: [Exercise]
    let result: PublishedResult?
    var fingerprint: String {
        struct Identity: Encodable {
            let id: Int; let pilot: Int; let instructor: Int; let session: TrainingTemplate
            let exercises: [Exercise]; let start: Date?; let end: Date?; let zone: String?; let venue: String?; let extra: Bool?
        }
        let identity = Identity(id: id, pilot: pilot.id, instructor: instructor.id, session: session,
            exercises: exercises, start: plannedAt, end: endsAt, zone: scheduleTimezone, venue: venue, extra: isExtra)
        return (try? Wire.encoder().encode(identity)).map(Wire.hash) ?? ""
    }
}

struct CompetencyGrade: Codable, Equatable {
    var score: Int = 0
    var remarks: String = ""
}
enum Competencies {
    static let all: [(String, String)] = [("pro","Процедуры"),("com","Коммуникация"),("fpa","Траектория: автоматика"),
        ("fpm","Траектория: ручное управление"),("ltw","Работа в экипаже"),("psd","Решение проблем"),
        ("saw","Ситуационная осведомлённость"),("wlm","Управление нагрузкой")]
}
struct ResultExercise: Codable, Equatable {
    let assignmentId: Int
    let exerciseName: String?
    let score: Int
    var grades: [String: CompetencyGrade]
    init(assignmentId: Int, exerciseName: String?, score: Int, grades: [String: CompetencyGrade]) {
        self.assignmentId = assignmentId; self.exerciseName = exerciseName; self.score = score; self.grades = grades
    }
    init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: DynamicKey.self)
        assignmentId = try box.decode(Int.self, forKey: DynamicKey("assignmentId"))
        exerciseName = try box.decodeIfPresent(String.self, forKey: DynamicKey("exerciseName"))
        score = try box.decode(Int.self, forKey: DynamicKey("score"))
        grades = [:]
        for (key, _) in Competencies.all {
            grades[key] = CompetencyGrade(score: try box.decodeIfPresent(Int.self, forKey: DynamicKey(key + "Score")) ?? 0,
                remarks: try box.decodeIfPresent(String.self, forKey: DynamicKey(key + "Remarks")) ?? "")
        }
    }
    func encode(to encoder: Encoder) throws {
        var box = encoder.container(keyedBy: DynamicKey.self)
        try box.encode(assignmentId, forKey: DynamicKey("assignmentId"))
        try box.encodeIfPresent(exerciseName, forKey: DynamicKey("exerciseName")); try box.encode(score, forKey: DynamicKey("score"))
        for (key, _) in Competencies.all {
            try box.encode(grades[key]?.score ?? 0, forKey: DynamicKey(key + "Score"))
            try box.encode(grades[key]?.remarks ?? "", forKey: DynamicKey(key + "Remarks"))
        }
    }
}
struct DynamicKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }
    init(_ value: String) { stringValue = value }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}
struct PublishedResult: Codable, Equatable, Identifiable {
    let id: Int
    let trainingId: Int?
    let pilot: Person
    let instructor: Person
    let session: TrainingTemplate
    let createdAt: Date?
    let generalNotes: String
    let exercises: [ResultExercise]
}
struct OfflineSnapshot: Codable {
    var assignments: [Assignment] = []
    var details: [Int: AssignmentDetail] = [:]
    var history: [Int: [PublishedResult]] = [:]
    var downloadedAt: Date?
}


struct HTTPFailure: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { "HTTP \(status). " + message }
    var definitelyRejected: Bool { (400...499).contains(status) && status != 408 && status != 499 }
    static func responseMessage(_ data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let direct = object["error"] as? String ?? object["detail"] as? String { return String(direct.prefix(1200)) }
        func flatten(_ value: Any, _ prefix: String, _ depth: Int) -> [String] {
            if depth > 5 { return [] }
            if let text = value as? String { return [prefix.isEmpty ? text : prefix + ": " + text] }
            if let array = value as? [Any] {
                return array.prefix(12).enumerated().flatMap { index, item in
                    flatten(item, item is [String: Any] ? prefix + "[\(index + 1)]" : prefix, depth + 1)
                }
            }
            if let dictionary = value as? [String: Any] {
                return dictionary.keys.sorted().flatMap { key in flatten(dictionary[key]!, prefix.isEmpty ? key : prefix + "." + key, depth + 1) }
            }
            return []
        }
        let lines = flatten(object, "", 0)
        return lines.isEmpty ? nil : String(lines.prefix(8).joined(separator: "\n").prefix(1200))
    }
}
enum PublicationStatus {
    static func afterFailure(_ error: Error, didSend: Bool) -> DraftDelivery {
        if !didSend || (error as? HTTPFailure)?.definitelyRejected == true { return .draft }
        return .uncertain
    }
}
