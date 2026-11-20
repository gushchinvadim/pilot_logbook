import { openPrintDocument } from './print-document.js';

const competencies = [
    ['pro', 'PRO — Процедуры'], ['com', 'COM — Коммуникация'],
    ['fpa', 'FPA — Автоматика'], ['fpm', 'FPM — Ручное управление'],
    ['ltw', 'LTW — Работа в команде'], ['psd', 'PSD — Решение проблем'],
    ['saw', 'SAW — Ситуационная осведомлённость'], ['wlm', 'WLM — Управление нагрузкой'],
];

export function draftKey(instructorId, trainingId) {
    return `simTraining:draft:v1:${instructorId}:${trainingId}`;
}

export function progress(draft, exercises) {
    return exercises.filter(ex => [2, 3, 4, 5].includes(Number(draft.exercises?.[ex.id]?.score))).length;
}

function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
}

function dateLabel(value) {
    return value ? new Date(value).toLocaleString('ru-RU') : 'Дата не назначена';
}

function errorText(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(errorText).join('; ');
    if (value && typeof value === 'object') return Object.entries(value).map(([key, val]) => `${key}: ${errorText(val)}`).join('; ');
    return 'Не удалось выполнить запрос';
}

export async function mountCrewSession(container) {
    if (!document.getElementById('crew-session-style')) {
        const css = document.createElement('link');
        css.id = 'crew-session-style'; css.rel = 'stylesheet'; css.href = '/static/css/crew-session.css';
        document.head.append(css);
    }
    const token = localStorage.getItem('authToken');
    const root = element('section', undefined, 'crew-workspace');
    container.replaceChildren(root);
    const message = element('p', 'Загрузка своих сессий…', 'crew-message');
    message.setAttribute('role', 'status');
    root.append(message);
    let instructorId, sessions = [], currentGroup = null, currentPilot = null;
    let exercises = [], draft = null, busy = false, revision = 0, storageFailed = false;
    const shell = element('div'); root.append(shell);
    let form = null, tabs = null;
    const drafts = new Map();

    function connected() {
        return root.isConnected && localStorage.getItem('authToken') === token;
    }
    async function api(url, options = {}) {
        if (localStorage.getItem('authToken') !== token) throw new Error('Учётная запись изменилась. Откройте сессию заново.');
        const response = await fetch(url, {...options, headers: {
            'Authorization': `Token ${token}`, 'Content-Type': 'application/json', ...options.headers,
        }});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(errorText(data.error || data.detail || data));
        return data;
    }
    function tell(text, error = false) {
        message.textContent = text; message.classList.toggle('crew-error', error);
    }
    function loadDraft(person) {
        if (person.result) return {
            general_notes: person.result.general_notes,
            exercises: Object.fromEntries(person.result.exercises.map(ex => [ex.assignment_id, {...ex}])),
        };
        if (drafts.has(person.id)) return drafts.get(person.id);
        let saved;
        try {
            const raw = localStorage.getItem(draftKey(instructorId, person.id));
            saved = raw ? JSON.parse(raw) : null;
            if (saved && (saved.training_id !== person.id || saved.pilot_id !== person.pilot.id ||
                saved.session_id !== currentGroup.session.id || !saved.exercises || typeof saved.exercises !== 'object')) {
                throw new Error('Несовместимый черновик');
            }
        } catch (error) {
            tell('Не удалось прочитать черновик. Данные оставлены в хранилище; переключение заблокировано до устранения ошибки.', true);
            throw error;
        }
        const value = saved || {training_id: person.id, pilot_id: person.pilot.id,
            session_id: currentGroup.session.id, general_notes: '', exercises: {}, scroll: 0};
        drafts.set(person.id, value);
        return value;
    }
    function persist() {
        if (!currentPilot || currentPilot.result || !draft) return true;
        try {
            if (localStorage.getItem('authToken') !== token) throw new Error('Учётная запись изменилась');
            draft.scroll = form?.scrollTop || 0;
            localStorage.setItem(draftKey(instructorId, currentPilot.id), JSON.stringify(draft));
            storageFailed = false;
            return true;
        } catch (error) {
            storageFailed = true;
            tell('Не удалось сохранить черновик на устройстве. Не закрывайте страницу и не переключайте пилота.', true);
            return false;
        }
    }
    function saveInput() {
        if (persist()) tell('Черновик этого пилота сохранён на устройстве. Оценки ещё не опубликованы.');
        renderTabs();
    }
    function renderTabs() {
        if (!tabs || !currentGroup) return;
        tabs.replaceChildren();
        for (const person of currentGroup.participants) {
            const saved = person.id === currentPilot?.id ? draft : loadDraft(person);
            const filled = progress(saved || {}, exercises);
            const button = element('button', undefined, 'crew-pilot-tab');
            button.type = 'button';
            button.setAttribute('aria-pressed', String(person.id === currentPilot?.id));
            button.append(element('strong', person.pilot.name), element('span', person.result ? 'Итоговые оценки сохранены' : `${filled} из ${exercises.length} упражнений`));
            button.disabled = busy;
            button.onclick = () => switchPilot(person);
            tabs.append(button);
        }
    }
    function field(label, input) {
        const wrapper = element('label', undefined, 'crew-field');
        wrapper.append(element('span', label), input); return wrapper;
    }
    function ratingSelect(value, allowZero, disabled) {
        const select = element('select');
        for (const [key, label] of allowZero ? [[0, 'Не оценивалось'], [1, '1 — Небезопасный'], [2, '2 — Минимально допустимый'], [3, '3 — Стандартный'], [4, '4 — Эффективный'], [5, '5 — Образцовый']] : [['', 'Выберите оценку'], [2, '2 — Неудовлетворительно'], [3, '3 — Удовлетворительно'], [4, '4 — Хорошо'], [5, '5 — Отлично']]) {
            const option = element('option', label); option.value = key; select.append(option);
        }
        select.value = value ?? (allowZero ? 0 : ''); select.disabled = disabled;
        return select;
    }
    function renderForm() {
        form.replaceChildren();
        if (!currentPilot || !draft) return;
        const person = currentPilot;
        const renderedDraft = draft;
        const readOnly = !!person.result || person.status !== 'planned';
        form.append(element('h3', person.pilot.name), element('p', `${dateLabel(person.planned_at)} · ${person.venue || 'Место не указано'}`, 'crew-muted'));
        if (person.result) {
            const link = element('button', 'Распечатать выполненное задание', 'crew-secondary'); link.type = 'button';
            link.onclick = async () => {
                try {
                    await openPrintDocument(`/api/results/${person.result.id}/print/`, token);
                } catch (error) { tell(error.message, true); }
            };
            form.append(element('p', 'Сохранённый результат доступен для просмотра. Изменения здесь запрещены.'), link);
        }
        exercises.forEach(ex => {
            const values = draft.exercises[ex.id] || {};
            const card = element('section', undefined, 'crew-exercise');
            card.append(element('h4', `${ex.order ?? ''}. ${ex.name}`), element('p', `${ex.phase_of_flight || '—'} · Минимальная оценка: ${ex.min_score}`, 'crew-muted'));
            if (Number(ex.duration_minutes) > 0) {
                const timer = element('span', '', 'crew-muted');
                const start = element('button', 'Начать отсчёт', 'crew-secondary'); start.type = 'button';
                start.disabled = readOnly;
                const tick = () => {
                    if (!timer.isConnected || draft !== renderedDraft) return;
                    const end = renderedDraft.timerEnds?.[ex.id];
                    const remaining = end ? Math.max(0, Math.ceil((end - Date.now()) / 1000)) : null;
                    timer.textContent = remaining === null ? `Рекомендуемое время: ${ex.duration_minutes} мин` :
                        `Осталось: ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`;
                    if (remaining > 0) window.setTimeout(tick, 1000);
                };
                start.onclick = () => {
                    (draft.timerEnds ||= {})[ex.id] = Date.now() + Number(ex.duration_minutes) * 60000;
                    persist(); tick();
                };
                card.append(timer, start);
                window.setTimeout(tick, 0);
            }
            const score = ratingSelect(values.score, false, readOnly);
            score.onchange = () => { (draft.exercises[ex.id] ||= {}).score = score.value ? Number(score.value) : null; saveInput(); };
            card.append(field('Общая оценка упражнения', score));
            const details = element('details');
            details.append(element('summary', 'Компетенции и замечания'));
            details.open = !!draft.openDetails?.[ex.id];
            details.ontoggle = () => {
                if (readOnly || !details.isConnected || draft !== renderedDraft) return;
                (draft.openDetails ||= {})[ex.id] = details.open; persist();
            };
            for (const [key, label] of competencies.filter(([key]) => !ex.required_competencies?.length || ex.required_competencies.includes(key))) {
                const compScore = ratingSelect(values[`${key}_score`], true, readOnly);
                const remarks = element('textarea'); remarks.value = values[`${key}_remarks`] || ''; remarks.rows = 2; remarks.disabled = readOnly;
                compScore.onchange = () => { (draft.exercises[ex.id] ||= {})[`${key}_score`] = Number(compScore.value); saveInput(); };
                remarks.oninput = () => { (draft.exercises[ex.id] ||= {})[`${key}_remarks`] = remarks.value; saveInput(); };
                const row = element('div', undefined, 'crew-competency');
                row.append(field(label, compScore), field(`Замечания: ${key.toUpperCase()}`, remarks)); details.append(row);
            }
            card.append(details); form.append(card);
        });
        const notes = element('textarea'); notes.value = draft.general_notes || ''; notes.rows = 4; notes.disabled = readOnly;
        notes.oninput = () => { draft.general_notes = notes.value; saveInput(); };
        form.append(field('Общие замечания по этому пилоту', notes));
        if (!readOnly) {
            const submit = element('button', 'Сохранить итоговые оценки этого пилота', 'crew-primary'); submit.type = 'button';
            submit.onclick = () => publish(submit); form.append(submit);
        }
        form.scrollTop = draft.scroll || 0;
    }
    function switchPilot(person) {
        if (busy || !persist()) return;
        try {
            const next = loadDraft(person);
            currentPilot = person; draft = next; renderTabs(); renderForm();
            if (!storageFailed) tell(person.result ? 'Открыт сохранённый результат.' : 'Открыт отдельный черновик выбранного пилота.');
        } catch (error) { /* The original storage entry is retained. */ }
    }
    async function publish(button) {
        if (busy || !persist()) return;
        if (progress(draft, exercises) !== exercises.length || !exercises.length) { tell('Заполните общие оценки всех упражнений.', true); return; }
        if (!window.confirm(`Сохранить итоговые оценки пилота «${currentPilot.pilot.name}»? Они станут доступны слушателю через сервер.`)) return;
        const person = currentPilot;
        const payload = {pilot_id: person.pilot.id, session_id: person.id,
            general_notes: draft.general_notes || '', exercises: exercises.map(ex => ({
                ...draft.exercises[ex.id], assignment_id: ex.id,
            }))};
        busy = true; button.disabled = true; form.inert = true; renderTabs();
        try {
            const result = await api('/api/rating-sessions/', {method: 'POST', body: JSON.stringify(payload)});
            person.result = {id: result.rating_session_id, general_notes: payload.general_notes, exercises: payload.exercises};
            person.status = 'completed'; person.has_result = true;
            try { localStorage.removeItem(draftKey(instructorId, person.id)); } catch (_) { /* The published snapshot has priority. */ }
            drafts.delete(person.id);
            tell('Итоговые оценки этого пилота сохранены на сервере. Второй пилот оценивается отдельно.');
        } catch (error) { tell(`${error.message}. Черновик остаётся на устройстве.`, true); }
        finally { busy = false; form.inert = false; if (connected()) { renderTabs(); renderForm(); } }
    }
    async function chooseGroup(group) {
        if (busy || !persist()) return;
        const request = ++revision;
        tell('Загрузка задания…');
        try {
            const loaded = await api(`/api/session/${group.session.id}/exercises/`);
            if (!connected() || request !== revision) return;
            currentGroup = group; exercises = loaded; currentPilot = null; draft = null;
            const first = group.participants.find(p => !p.result && p.status === 'planned') || group.participants[0];
            const body = shell.querySelector('.crew-body'); body.replaceChildren();
            const heading = element('h2', group.session.title);
            const subtitle = element('p', group.crew_id ? 'Экипаж · отдельные результаты каждого пилота' : 'Индивидуальная запись · можно связать со вторым пилотом', 'crew-muted');
            tabs = element('div', undefined, 'crew-pilot-tabs'); tabs.setAttribute('aria-label', 'Выбор пилота');
            form = element('div', undefined, 'crew-pilot-form');
            body.append(heading, subtitle, tabs, form); switchPilot(first);
        } catch (error) { tell(error.message, true); }
    }
    function renderPairing() {
        const available = sessions.filter(s => !s.crew_id && s.participants.length === 1);
        const details = element('details', undefined, 'crew-pairing'); details.append(element('summary', 'Связать две существующие записи в экипаж'));
        details.append(element('p', 'Выберите две записи одного задания и инструктора. Их даты, оценки и печатные документы сохранятся.'));
        const selects = [element('select'), element('select')];
        selects.forEach(select => {
            const placeholder = element('option', 'Выберите запись'); placeholder.value = ''; select.append(placeholder);
            available.forEach(group => {
                const person = group.participants[0];
                const option = element('option', `${person.pilot.name} · ${group.session.title} · ${dateLabel(person.planned_at)}`);
                option.value = person.id; select.append(option);
            });
        });
        const pair = element('button', 'Объединить выбранные записи', 'crew-secondary'); pair.type = 'button';
        pair.onclick = async () => {
            if (busy || !persist()) return;
            const ids = selects.map(s => Number(s.value));
            if (!ids[0] || !ids[1] || ids[0] === ids[1]) { tell('Выберите две разные записи.', true); return; }
            if (!window.confirm(`Связать выбранные записи?\n${selects.map(s => s.selectedOptions[0].textContent).join('\n')}`)) return;
            busy = true; pair.disabled = true;
            try {
                const result = await api('/api/crew-sessions/', {method: 'POST', body: JSON.stringify({training_ids: ids})});
                await refresh(result.crew_id);
            } catch (error) { tell(error.message, true); }
            finally { busy = false; pair.disabled = false; }
        };
        details.append(field('Первый пилот', selects[0]), field('Второй пилот', selects[1]), pair);
        return details;
    }
    async function refresh(selectedCrewId) {
        const data = await api('/api/crew-sessions/');
        if (!connected()) return;
        instructorId = data.instructor_id; sessions = data.sessions;
        shell.replaceChildren();
        const selector = element('select');
        selector.setAttribute('aria-label', 'Тренажёрная сессия');
        const placeholder = element('option', 'Выберите сессию'); placeholder.value = ''; selector.append(placeholder);
        sessions.forEach(group => {
            const option = element('option', `${group.session.title} · ${group.participants.map(p => p.pilot.name).join(' / ')} · ${dateLabel(group.participants[0].planned_at)}`);
            option.value = group.key; selector.append(option);
        });
        selector.onchange = async () => {
            const group = sessions.find(s => s.key === selector.value);
            if (!group || busy) { selector.value = currentGroup?.key || ''; return; }
            if (!persist()) { selector.value = currentGroup?.key || ''; return; }
            await chooseGroup(group);
        };
        shell.append(field('Тренажёрная сессия и экипаж', selector), renderPairing(), element('div', undefined, 'crew-body'));
        if (!sessions.length) tell('Назначенных сессий пока нет.');
        else tell('Выберите сессию. Черновики каждого пилота сохраняются отдельно на этом устройстве.');
        const selected = sessions.find(s => s.crew_id === selectedCrewId);
        if (selected) { selector.value = selected.key; busy = false; await chooseGroup(selected); }
    }
    try { await refresh(); } catch (error) { tell(error.message, true); }
}
