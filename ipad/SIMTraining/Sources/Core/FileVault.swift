import Foundation

final class FileVault {
    let directory: URL
    init(root: URL, server: String, userId: Int) throws {
        let scope = Wire.hash(Data((server + "#" + String(userId)).utf8))
        directory = root.appendingPathComponent("SIMTraining/Accounts", isDirectory: true).appendingPathComponent(scope, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700])
        var url = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
    }
    func snapshot() throws -> OfflineSnapshot {
        let url = directory.appendingPathComponent("snapshot.json")
        if !FileManager.default.fileExists(atPath: url.path) { return OfflineSnapshot() }
        return try Wire.decoder().decode(OfflineSnapshot.self, from: Data(contentsOf: url))
    }
    func save(snapshot: OfflineSnapshot) throws { try write(Wire.encoder().encode(snapshot), to: "snapshot.json") }
    func save(draft: TrainingDraft) throws { try write(Wire.encoder().encode(draft), to: "draft-\(draft.id).json") }
    func drafts() throws -> [Int: TrainingDraft] {
        var result: [Int: TrainingDraft] = [:]
        for file in try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            where file.lastPathComponent.hasPrefix("draft-") && file.pathExtension == "json" {
            let draft = try Wire.decoder().decode(TrainingDraft.self, from: Data(contentsOf: file))
            result[draft.id] = draft
        }
        return result
    }
    private func write(_ data: Data, to name: String) throws {
        let url = directory.appendingPathComponent(name)
        #if os(iOS)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        #else
        try data.write(to: url, options: .atomic)
        #endif
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}
