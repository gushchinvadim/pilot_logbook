import SwiftUI

enum PortalPage: String, CaseIterable, Identifiable, Hashable {
    case calendar = "Календарь", drafts = "Черновики", device = "Данные на iPad"
    var id: String { rawValue }
    var icon: String { switch self { case .calendar: return "calendar"; case .drafts: return "square.and.pencil"; case .device: return "ipad" } }
}
struct RootView: View {
    @EnvironmentObject private var state: AppState
    @State private var page: PortalPage? = .calendar
    @State private var confirmLogout = false
    var body: some View {
        Group {
            if state.profile == nil {
                if state.bootstrapped { LoginView() } else { ProgressView("Открываем SIM Training…") }
            } else {
                NavigationSplitView {
                    List(selection: $page) {
                        Section {
                            Label("SIM Training", systemImage: "airplane").font(.title2.bold()).padding(.vertical, 8)
                            Text("BOEING 737NG\nРабочее место инструктора").font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(PortalPage.allCases) { item in
                            Label(item.rawValue, systemImage: item.icon).tag(item)
                        }
                        Section("Инструктор") { Text(state.profile?.name ?? ""); Text(state.serverName).font(.caption).foregroundStyle(.secondary) }
                        Button("Выйти", systemImage: "rectangle.portrait.and.arrow.right") { confirmLogout = true }.disabled(state.busy || state.storageError != nil)
                    }.navigationTitle("SIM Training")
                } detail: {
                    NavigationStack {
                        VStack(spacing: 0) {
                            MessageBar()
                            switch page ?? .calendar {
                            case .calendar: CalendarView()
                            case .drafts: DraftListView()
                            case .device: DeviceView()
                            }
                        }
                        .toolbar {
                            ToolbarItem(placement: .topBarTrailing) {
                                Button { Task { await state.refresh() } } label: {
                                    Label("Загрузить задания", systemImage: "arrow.triangle.2.circlepath")
                                }.disabled(state.busy)
                            }
                        }
                    }
                }
                .confirmationDialog("Выйти из учётной записи? Черновики останутся на этом iPad и будут доступны после входа под той же учётной записью.", isPresented: $confirmLogout, titleVisibility: .visible) {
                    Button("Выйти", role: .destructive) { state.logout() }
                    Button("Отмена", role: .cancel) {}
                }
            }
        }
    }
}
struct LoginView: View {
    @EnvironmentObject private var state: AppState
    @State private var username = ""
    @State private var password = ""
    @State private var server = "https://type-rating.survey-ebt.ru"
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Image(systemName: "airplane.circle.fill").font(.system(size: 64)).foregroundStyle(.tint)
                Text("SIM Training").font(.largeTitle.bold())
                Text("Boeing 737NG · GVE Dynamics").font(.headline).foregroundStyle(.secondary)
                Text("Войдите под своей учётной записью инструктора. Перед работой без сети загрузите календарь и задания.")
                VStack(spacing: 16) {
                    TextField("Логин", text: $username).textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("Пароль", text: $password).textContentType(.password)
                }.textFieldStyle(.roundedBorder)
                #if DEBUG
                DisclosureGroup("Сервер для разработки") {
                    TextField("Адрес сервера", text: $server).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Text("На физическом iPad localhost означает сам iPad. Для локального Django нужен адрес Mac в сети.").font(.caption).foregroundStyle(.secondary)
                }
                #endif
                if let error = state.error { Text(error).foregroundStyle(.red).accessibilityLabel("Ошибка: " + error) }
                Button {
                    Task {
                        let success = await state.login(server: server, username: username, password: password)
                        password = ""
                        if success { username = "" }
                    }
                } label: { HStack { Spacer(); if state.busy { ProgressView() }; Text(state.busy ? "Входим…" : "Войти"); Spacer() }.padding(10) }
                .buttonStyle(.borderedProminent).disabled(state.busy || username.trimmingCharacters(in: .whitespaces).isEmpty || password.isEmpty)
            }.padding(40).frame(maxWidth: 540)
        }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Color(.systemGroupedBackground))
    }
}
struct MessageBar: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if state.busy { HStack { ProgressView(); Text(state.progress.isEmpty ? "Обращаемся к серверу…" : state.progress) }.font(.callout) }
            if let storage = state.storageError {
                Text(storage).foregroundStyle(.red)
                Button("Повторить сохранение на iPad") { state.retryLocalSave() }
            }
            if let error = state.error {
                HStack(alignment: .top) { Image(systemName: "exclamationmark.triangle"); Text(error); Spacer(); Button("Скрыть") { state.error = nil } }
                    .foregroundStyle(.red).font(.callout)
            }
            if let notice = state.notice {
                HStack(alignment: .top) { Image(systemName: "checkmark.circle"); Text(notice); Spacer(); Button("Скрыть") { state.notice = nil } }.font(.callout)
            }
        }.padding(state.busy || state.error != nil || state.notice != nil || state.storageError != nil ? 14 : 0)
        .frame(maxWidth: .infinity, alignment: .leading).background(Color(.secondarySystemGroupedBackground))
    }
}
struct AssignmentGroup: Identifiable {
    let id: String
    let rows: [Assignment]
    var first: Assignment { rows[0] }
    var names: String { rows.map { $0.pilot.name }.joined(separator: " / ") }
    var statusText: String {
        if rows.contains(where: { $0.status == "planned" }) { return "Запланирована" }
        if rows.allSatisfy({ $0.status == "completed" }) { return "Проведена" }
        if rows.allSatisfy({ $0.status == "cancelled" }) { return "Отменена" }
        return "Частично проведена"
    }
}
struct CalendarView: View {
    @EnvironmentObject private var state: AppState
    @State private var day = Date()
    private var dayKey: String {
        let formatter = DateFormatter(); formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: day)
    }
    private var groups: [AssignmentGroup] {
        Dictionary(grouping: state.assignments, by: \.groupKey).map { AssignmentGroup(id: $0.key, rows: $0.value.sorted { $0.pilot.id < $1.pilot.id }) }
            .sorted { ($0.first.plannedAt ?? .distantFuture) < ($1.first.plannedAt ?? .distantFuture) }
    }
    var body: some View {
        List {
            Section {
                DatePicker("Дата расписания", selection: $day, displayedComponents: .date).datePickerStyle(.graphical).labelsHidden()
                    .environment(\.locale, Locale(identifier: "ru_RU"))
            } footer: { Text("Дата и время каждого занятия — по месту тренажёра.") }
            Section("На выбранную дату") {
                let selected = groups.filter { $0.first.localDay == dayKey }
                if selected.isEmpty { Text("На эту дату назначений нет.").foregroundStyle(.secondary) }
                ForEach(selected) { group in row(group) }
            }
            Section("Ближайшие запланированные сессии") {
                let upcoming = groups.filter { $0.rows.contains { $0.status == "planned" } && ($0.first.endsAt ?? $0.first.plannedAt ?? .distantFuture) >= Date() }
                if upcoming.isEmpty { Text("Будущие назначения появятся после загрузки расписания.").foregroundStyle(.secondary) }
                ForEach(Array(upcoming.prefix(12))) { group in row(group) }
            }
        }.navigationTitle("Календарь сессий")
        .refreshable { await state.refresh() }
    }
    private func row(_ group: AssignmentGroup) -> some View {
        NavigationLink { WorkspaceView(ids: group.rows.map(\.id)) } label: {
            VStack(alignment: .leading, spacing: 6) {
                HStack { if group.first.isExtra == true { Text("EXTRA").font(.caption.bold()).foregroundStyle(.orange) }; Text(group.first.session.title).font(.headline) }
                Text(group.names).font(.subheadline)
                Text(group.first.timeText).font(.caption).foregroundStyle(.secondary)
                Text([group.first.venue ?? "", group.statusText].filter { !$0.isEmpty }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
            }.padding(.vertical, 5)
        }
    }
}
struct DraftListView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        List {
            if state.pendingDrafts.isEmpty { ContentUnavailableView("Черновиков пока нет", systemImage: "square.and.pencil", description: Text("Откройте назначенное занятие и начните оценивание.")) }
            ForEach(state.pendingDrafts) { draft in
                NavigationLink { WorkspaceView(ids: [draft.id]) } label: {
                    VStack(alignment: .leading, spacing: 5) {
                        Text(state.detail(draft.id)?.session.title ?? "Сохранённое задание").font(.headline)
                        Text(state.detail(draft.id)?.pilot.name ?? "Пилот").font(.subheadline)
                        Text(draft.delivery == .uncertain ? "Требуется проверка сохранения на сервере" : "Оценено упражнений: \(draft.completedCount)").font(.caption).foregroundStyle(.secondary)
                        if state.assignment(draft.id) == nil { Text("Назначение отсутствует в актуальном календаре. Черновик сохранён для проверки.").font(.caption).foregroundStyle(.orange) }
                    }
                }
            }
        }.navigationTitle("Черновики на iPad")
    }
}
struct DeviceView: View {
    @EnvironmentObject private var state: AppState
    var body: some View {
        Form {
            Section("Загружено для работы без сети") {
                LabeledContent("Назначений", value: String(state.assignments.count))
                LabeledContent("Заданий", value: String(state.snapshot.details.count))
                LabeledContent("Незавершённых черновиков", value: String(state.pendingDrafts.count))
                if let date = state.snapshot.downloadedAt { LabeledContent("Последняя загрузка", value: date.formatted(date: .abbreviated, time: .shortened)) }
            }
            Section("Работа с результатами") {
                Text("Оценки и замечания сохраняются на этом iPad после каждого изменения. Для итоговой отправки нужен интернет и отдельное подтверждение.")
                Text("Если связь оборвётся во время отправки, черновик останется на устройстве. Кнопка проверки позволит узнать, сохранился ли результат на сервере.")
            }
            Section("Учётная запись") { Text(state.profile?.name ?? ""); Text(state.serverName) }
        }.navigationTitle("Данные на iPad")
    }
}
