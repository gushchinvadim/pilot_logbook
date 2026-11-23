import Foundation
import Combine

@MainActor final class AppState: ObservableObject {
    @Published private(set) var profile: Profile?
    @Published private(set) var snapshot = OfflineSnapshot()
    @Published private(set) var drafts: [Int: TrainingDraft] = [:]
    @Published private(set) var busy = false
    @Published private(set) var bootstrapped = false
    @Published var error: String?
    @Published var notice: String?
    @Published private(set) var storageError: String?
    @Published private(set) var progress = ""
    private var api: SIMAPI?
    private var vault: FileVault?
    private var unsavedDraftIds: Set<Int> = []
    var serverName: String { api?.server.host ?? "SIM Training" }
    var assignments: [Assignment] {
        snapshot.assignments.filter { $0.instructorId == profile?.instructorId }
    }
    var pendingDrafts: [TrainingDraft] {
        drafts.values.filter { $0.delivery != .published }.sorted { $0.updatedAt > $1.updatedAt }
    }
    func restore() async {
        guard !bootstrapped else { return }
        defer { bootstrapped = true }
        do {
            if let credentials = try SecureSession.load() {
                try install(credentials)
                await refresh()
            }
        } catch { self.error = "Не удалось открыть сохранённые данные. Файлы черновиков не удалены. " + error.localizedDescription }
    }
    func login(server: String, username: String, password: String) async -> Bool {
        guard !busy else { return false }
        busy = true; error = nil; notice = nil
        do {
            let client = try SIMAPI(server: server)
            let user = try await client.login(username: username.trimmingCharacters(in: .whitespacesAndNewlines), password: password)
            guard let token = client.token else { throw APIError.unauthorized }
            let credentials = Credentials(server: client.normalizedServer, token: token, profile: user)
            try SecureSession.save(credentials); try install(credentials)
            busy = false
            await refresh()
            return true
        } catch { self.error = error.localizedDescription; busy = false; return false }
    }
    private func install(_ credentials: Credentials) throws {
        guard credentials.profile.isInstructor else { throw APIError.unauthorized }
        let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let files = try FileVault(root: root, server: credentials.server, userId: credentials.profile.id)
        let cached = try files.snapshot(), localDrafts = try files.drafts()
        api = try SIMAPI(server: credentials.server, token: credentials.token)
        vault = files; snapshot = cached; drafts = localDrafts; profile = credentials.profile
    }
    func logout() {
        guard unsavedDraftIds.isEmpty else { storageError = "Сначала сохраните последние изменения на iPad."; return }
        SecureSession.clear(); api = nil; vault = nil; profile = nil
        snapshot = OfflineSnapshot(); drafts = [:]; error = nil; notice = nil; storageError = nil
    }
    func refresh() async {
        guard !busy, let api, let vault, let profile else { return }
        busy = true; error = nil; notice = nil; progress = "Получаем календарь…"
        defer { busy = false; progress = "" }
        do {
            let current: Profile = try await api.request("/api/auth/me/")
            guard current.id == profile.id, current.instructorId == profile.instructorId, current.isInstructor else {
                throw APIError.message("Профиль инструктора изменился. Войдите заново. Локальные черновики сохранены.")
            }
            let rows: [Assignment] = try await api.request("/api/my-training-sessions/")
            var next = snapshot
            next.assignments = rows.filter { $0.instructorId == current.instructorId }
            for (index, row) in next.assignments.enumerated() {
                progress = "Загружаем задания: \(index + 1) / \(next.assignments.count)"
                let detail: AssignmentDetail = try await api.request("/api/training-sessions/\(row.id)/")
                guard detail.id == row.id, detail.instructor.id == current.instructorId, detail.pilot.id == row.pilot.id else {
                    throw APIError.message("Сервер вернул назначение другого участника. Загрузка остановлена.")
                }
                next.details[row.id] = detail
            }
            for pilotId in Set(next.assignments.map { $0.pilot.id }).sorted() {
                progress = "Загружаем предыдущие замечания…"
                let results: [PublishedResult] = try await api.request("/api/results/?pilot_id=\(pilotId)")
                guard results.allSatisfy({ $0.pilot.id == pilotId }) else { throw APIError.message("Не удалось проверить принадлежность результатов.") }
                next.history[pilotId] = results
            }
            next.downloadedAt = Date()
            try vault.save(snapshot: next)
            snapshot = next
            notice = "Задания загружены. Их можно открыть без сети."
        } catch { self.error = error.localizedDescription }
    }
    func detail(_ id: Int) -> AssignmentDetail? { snapshot.details[id] }
    func assignment(_ id: Int) -> Assignment? { assignments.first { $0.id == id } }
    func canEdit(_ detail: AssignmentDetail) -> Bool {
        !busy && detail.instructor.id == profile?.instructorId && assignment(detail.id)?.status == "planned" &&
        detail.result == nil && drafts[detail.id]?.delivery != .published && drafts[detail.id]?.delivery != .uncertain &&
        (drafts[detail.id] == nil || drafts[detail.id]?.fingerprint == detail.fingerprint)
    }
    func edit(_ detail: AssignmentDetail, change: (inout TrainingDraft) -> Void) {
        guard canEdit(detail) else { return }
        var draft = drafts[detail.id] ?? TrainingDraft(detail: detail)
        change(&draft); draft.lastSubmissionMessage = nil; draft.updatedAt = Date()
        drafts[detail.id] = draft
        save(draft)
    }
    private func save(_ draft: TrainingDraft) {
        do {
            guard let vault else { return }
            try vault.save(draft: draft)
            unsavedDraftIds.remove(draft.id)
            if unsavedDraftIds.isEmpty { storageError = nil }
        } catch {
            unsavedDraftIds.insert(draft.id)
            storageError = "Не удалось сохранить последние изменения на iPad. Не закрывайте приложение; повторите сохранение."
        }
    }
    func retryLocalSave() {
        for draft in drafts.values { save(draft) }
    }
    private func cacheDetail(_ detail: AssignmentDetail) {
        snapshot.details[detail.id] = detail
        if let index = snapshot.assignments.firstIndex(where: { $0.id == detail.id }) { snapshot.assignments[index].status = detail.status }
        do { try vault?.save(snapshot: snapshot) }
        catch { self.error = "Ответ сервера получен, но не удалось обновить локальную копию задания." }
    }
    func verify(_ id: Int) async {
        guard !busy, let api, var draft = drafts[id] else { return }
        busy = true; error = nil; notice = nil
        defer { busy = false }
        do {
            let remote: AssignmentDetail = try await api.request("/api/training-sessions/\(id)/")
            cacheDetail(remote)
            if let result = remote.result {
                guard draft.matches(result, detail: remote) else { throw APIError.message("На сервере опубликован другой результат. Локальный черновик сохранён для проверки ответственным.") }
                draft.delivery = .published; draft.lastSubmissionMessage = nil; draft.publishedResultId = result.id
                drafts[id] = draft; save(draft); notice = "Результат подтверждён сервером."
            } else {
                draft.delivery = .draft; draft.lastSubmissionMessage = "Сервер пока не сохранил этот результат. Можно повторить отправку."; drafts[id] = draft; save(draft)
                notice = "Результат ещё не опубликован. Проверьте черновик перед повторной отправкой."
            }
        } catch {
            draft.lastSubmissionMessage = error.localizedDescription
            drafts[id] = draft; save(draft)
            self.error = error.localizedDescription
        }
    }
    func publish(_ id: Int) async {
        guard !busy, storageError == nil, let api, var draft = drafts[id], let cached = detail(id) else { return }
        busy = true; error = nil; notice = nil
        defer { busy = false }
        var didSend = false
        do {
            let remote: AssignmentDetail = try await api.request("/api/training-sessions/\(id)/")
            cacheDetail(remote)
            if let result = remote.result {
                guard draft.matches(result, detail: remote) else { throw APIError.message("На сервере уже есть другой результат. Черновик сохранён; требуется проверка ответственным.") }
                draft.delivery = .published; draft.lastSubmissionMessage = nil; draft.publishedResultId = result.id
                drafts[id] = draft; save(draft); notice = "Результат уже сохранён на сервере."
                return
            }
            guard remote.status == "planned", remote.instructor.id == profile?.instructorId,
                  remote.fingerprint == cached.fingerprint else { throw DraftError.changedAssignment }
            let body = try draft.payload(for: remote)
            // Persist uncertainty BEFORE sending: a timeout must never lose a finished result.
            draft.delivery = .uncertain; draft.lastSubmissionMessage = nil
            guard let vault else { throw APIError.message("Локальное сохранение недоступно.") }
            try vault.save(draft: draft); drafts[id] = draft
            struct Receipt: Decodable { let ratingSessionId: Int }
            didSend = true
            let receipt: Receipt = try await api.request("/api/rating-sessions/", method: "POST", body: body)
            draft.delivery = .published; draft.lastSubmissionMessage = nil; draft.publishedResultId = receipt.ratingSessionId
            drafts[id] = draft; save(draft)
            if let index = snapshot.assignments.firstIndex(where: { $0.id == id }) { snapshot.assignments[index].status = "completed" }
            try? vault.save(snapshot: snapshot)
            notice = "Итоговые оценки сохранены на сервере."
        } catch {
            draft.delivery = PublicationStatus.afterFailure(error, didSend: didSend)
            draft.lastSubmissionMessage = error.localizedDescription
            drafts[id] = draft; save(draft)
            self.error = error.localizedDescription
        }
    }
}
