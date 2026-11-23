import SwiftUI

struct WorkspaceView: View {
    @EnvironmentObject private var state: AppState
    let ids: [Int]
    @State private var selected: Int
    @State private var confirmPublish = false
    init(ids: [Int]) { self.ids = ids; _selected = State(initialValue: ids.first ?? 0) }
    private var detail: AssignmentDetail? { state.detail(selected) }
    var body: some View {
        Group {
            if let detail {
                workspace(detail)
            } else {
                ContentUnavailableView("Задание не загружено", systemImage: "arrow.down.circle", description: Text("Подключитесь к серверу и загрузите задания перед работой без сети."))
            }
        }.navigationTitle("Оценивание подготовки").navigationBarTitleDisplayMode(.inline)
    }
    private func workspace(_ detail: AssignmentDetail) -> some View {
        Form {
            Section {
                if ids.count > 1 {
                    Picker("Пилот", selection: $selected) { ForEach(ids, id: \.self) { id in Text(state.detail(id)?.pilot.name ?? "Пилот").tag(id) } }.pickerStyle(.segmented)
                }
                if detail.isExtra == true { Text("EXTRA · Дополнительная сессия").font(.caption.bold()).foregroundStyle(.orange) }
                Text(detail.session.title).font(.title2.bold())
                Text(detail.pilot.name).font(.headline)
                if let summary = state.assignment(detail.id) { Text(summary.timeText).font(.subheadline).foregroundStyle(.secondary); Text(summary.venue ?? "") }
                if let reason = detail.extraReason, !reason.isEmpty { Text("Цель: " + reason) }
                if let description = detail.session.description, !description.isEmpty { Text(description) }
            }
            if let result = detail.result {
                Section("Опубликованный результат") { ResultContent(result: result) }
            } else {
                draftStatus(detail)
                ForEach(detail.exercises) { exercise in
                    Section {
                        if !exercise.description.isEmpty { Text(exercise.description).font(.subheadline).foregroundStyle(.secondary) }
                        Text([exercise.phaseOfFlight, "Мин. оценка: \(exercise.minScore)"]
                            .filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                        Picker("Общая оценка", selection: scoreBinding(detail, exercise.id)) {
                            Text("—").tag(0)
                            ForEach(2...5, id: \.self) { Text(String($0)).tag($0) }
                        }.pickerStyle(.segmented).disabled(!state.canEdit(detail))
                        if exercise.hasUnsupportedCompetencies {
                            Text("В задании есть новые компетенции. Обновите приложение перед отправкой результата.").font(.caption).foregroundStyle(.orange)
                        }
                        if !exercise.selectedCompetencies.isEmpty {
                            DisclosureGroup("Компетенции и замечания") {
                                ForEach(exercise.selectedCompetencies, id: \.0) { code, label in
                                    VStack(alignment: .leading, spacing: 8) {
                                        Text(code.uppercased() + " · " + label).font(.subheadline.bold())
                                        Picker(label, selection: competencyScore(detail, exercise.id, code)) {
                                            Text("—").tag(0)
                                            ForEach(1...5, id: \.self) { Text(String($0)).tag($0) }
                                        }.pickerStyle(.segmented)
                                        TextField("Замечания", text: remarks(detail, exercise.id, code), axis: .vertical).lineLimit(2...6)
                                    }.padding(.vertical, 8).disabled(!state.canEdit(detail))
                                }
                            }
                        }
                    } header: { Text("\(exercise.order.map(String.init) ?? "—"). \(exercise.name)") }
                }
                Section("Общие замечания по сессии") {
                    TextEditor(text: generalNotes(detail)).frame(minHeight: 120).disabled(!state.canEdit(detail))
                }
                Section {
                    if let message = state.drafts[detail.id]?.lastSubmissionMessage {
                        Text(message).font(.callout).foregroundStyle(.orange)
                    }
                    if state.drafts[detail.id]?.delivery == .uncertain {
                        Text("Отправка ещё не подтверждена. Нажмите «Проверить сохранение на сервере».").font(.callout).foregroundStyle(.orange)
                    }
                    Button("Сохранить итоговые оценки на сервере") { confirmPublish = true }
                        .disabled(!canPublish(detail))
                    Text("После сохранения слушатель получит результат через сервер. Исправления опубликованного результата выполняет ответственный.").font(.caption).foregroundStyle(.secondary)
                }
            }
            if let draft = state.drafts[detail.id], draft.delivery == .uncertain || detail.result != nil && draft.delivery != .published {
                Section {
                    Button("Проверить сохранение на сервере") { Task { await state.verify(detail.id) } }.disabled(state.busy)
                    Text("Локальный черновик сохраняется до проверки результата.").font(.caption).foregroundStyle(.secondary)
                }
            }
            previousResults(detail)
        }
        .confirmationDialog("Сохранить итоговые оценки пилота «\(detail.pilot.name)»?", isPresented: $confirmPublish, titleVisibility: .visible) {
            Button("Сохранить итоговый результат") { Task { await state.publish(detail.id) } }
            Button("Отмена", role: .cancel) {}
        }
    }
    @ViewBuilder private func draftStatus(_ detail: AssignmentDetail) -> some View {
        Section {
            let count = detail.exercises.filter { (2...5).contains(state.drafts[detail.id]?.exercises[$0.id]?.score ?? 0) }.count
            ProgressView("Оценено: \(count) / \(detail.exercises.count)", value: Double(count), total: Double(max(detail.exercises.count, 1)))
            if let draft = state.drafts[detail.id] {
                if draft.delivery == .published { Label("Результат сохранён на сервере. Загрузите данные, чтобы открыть опубликованную версию.", systemImage: "checkmark.circle").foregroundStyle(.green) }
                else if draft.delivery == .uncertain { Label("Проверьте, получил ли сервер результат. Оценки остались на iPad.", systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
                else if state.storageError == nil { Label("Черновик на iPad · " + draft.updatedAt.formatted(date: .omitted, time: .standard), systemImage: "internaldrive") }
                if draft.fingerprint != detail.fingerprint { Text("Назначение изменилось. Черновик сохранён, отправка остановлена до проверки ответственным.").foregroundStyle(.orange) }
            } else { Text("Начните оценивание — изменения будут сохраняться на iPad.").font(.caption).foregroundStyle(.secondary) }
            if state.assignment(detail.id)?.status == "cancelled" { Text("Назначение отменено. Черновик доступен для просмотра.").foregroundStyle(.orange) }
        }
    }
    private func canPublish(_ detail: AssignmentDetail) -> Bool {
        guard state.canEdit(detail), state.storageError == nil, let draft = state.drafts[detail.id] else { return false }
        return (try? draft.payload(for: detail)) != nil
    }
    private func scoreBinding(_ detail: AssignmentDetail, _ id: Int) -> Binding<Int> {
        Binding(get: { state.drafts[detail.id]?.exercises[id]?.score ?? 0 }, set: { value in
            state.edit(detail) { draft in var item = draft.exercises[id] ?? ExerciseDraft(); item.score = value == 0 ? nil : value; draft.exercises[id] = item }
        })
    }
    private func competencyScore(_ detail: AssignmentDetail, _ id: Int, _ code: String) -> Binding<Int> {
        Binding(get: { state.drafts[detail.id]?.exercises[id]?.grades[code]?.score ?? 0 }, set: { value in
            state.edit(detail) { draft in var item = draft.exercises[id] ?? ExerciseDraft(); var grade = item.grades[code] ?? CompetencyGrade(); grade.score = value; item.grades[code] = grade; draft.exercises[id] = item }
        })
    }
    private func remarks(_ detail: AssignmentDetail, _ id: Int, _ code: String) -> Binding<String> {
        Binding(get: { state.drafts[detail.id]?.exercises[id]?.grades[code]?.remarks ?? "" }, set: { value in
            state.edit(detail) { draft in var item = draft.exercises[id] ?? ExerciseDraft(); var grade = item.grades[code] ?? CompetencyGrade(); grade.remarks = value; item.grades[code] = grade; draft.exercises[id] = item }
        })
    }
    private func generalNotes(_ detail: AssignmentDetail) -> Binding<String> {
        Binding(get: { state.drafts[detail.id]?.generalNotes ?? "" }, set: { value in state.edit(detail) { $0.generalNotes = value } })
    }
    @ViewBuilder private func previousResults(_ detail: AssignmentDetail) -> some View {
        let results = (state.snapshot.history[detail.pilot.id] ?? []).filter { $0.trainingId != detail.id }
        Section("Предыдущие замечания инструкторов") {
            if results.isEmpty { Text("Загруженных предыдущих результатов пока нет.").foregroundStyle(.secondary) }
            ForEach(results) { result in
                DisclosureGroup(result.session.title + " · " + result.instructor.name) { ResultContent(result: result) }
            }
        }
    }
}
struct ResultContent: View {
    let result: PublishedResult
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(result.instructor.name).font(.headline)
            if let date = result.createdAt { Text(date.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary) }
            if !result.generalNotes.isEmpty { Text(result.generalNotes) }
            ForEach(result.exercises, id: \.assignmentId) { exercise in
                VStack(alignment: .leading, spacing: 6) {
                    Text((exercise.exerciseName ?? "Упражнение") + " · \(exercise.score)").font(.subheadline.bold())
                    ForEach(Competencies.all, id: \.0) { code, _ in
                        if let grade = exercise.grades[code], !grade.remarks.isEmpty {
                            Text(code.uppercased() + ": " + grade.remarks).font(.subheadline)
                        }
                    }
                }
            }
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
    }
}
