function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}


//вход
//let authToken = localStorage.getItem('authToken');// ✅ Удаляем глобальную переменную authToken — она больше не нужна
let instructorId = null;



// Вспомогательная функция: получает заголовки авторизации
function getAuthHeaders() {
    const token = localStorage.getItem('authToken');
    return token ? { 'Authorization': `Token ${token}` } : {};
}

// Проверка сессии при загрузке
window.onload = function() {
    const name = localStorage.getItem('instructorName');
    const authToken = localStorage.getItem('authToken'); // ← берём из localStorage

    if (authToken && name) {
        // Уже авторизован
        document.getElementById('login-link').style.display = 'none';
        document.getElementById('logout-link').style.display = 'block';
        document.getElementById('user-info').innerHTML = `
            <p style="color: green;">Добро пожаловать, <strong>${escapeHtml(name)}</strong></p>
        `;
        document.querySelector('.login-container').style.display = 'none';
        document.querySelector('.button-container').style.display = 'flex';
        document.getElementById('content-area').style.display = 'block';

        // Опционально: загрузить календарь
        // showCalendar();
    } else {
        // Не авторизован
        document.getElementById('logout-link').style.display = 'none';
        document.querySelector('.button-container').style.display = 'none';
        document.getElementById('content-area').style.display = 'none';
    }
};

// Функция входа
function login() {
    console.log("🚀 Выполняем вход...");
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    fetch('/api/api-token-auth/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    })
    .then(r => {
        if (!r.ok) {
            throw new Error('Доступ запрещён! Свяжитесь с администратором.');
        }
        return r.json();
    })
    .then(data => {
        localStorage.setItem('authToken', data.token);

        // Запрашиваем данные инструктора
        return fetch('/api/instructor/current/', {
            headers: getAuthHeaders()
        });
    })
    .then(r => {
        if (!r.ok) {
            // Явно обрабатываем 404 / 403 как ошибку "не инструктор"
            return r.json().then(err => {
                throw new Error(err.error || 'Доступ запрещён: вы не являетесь инструктором в данной серии сессий.');
            });
        }
        return r.json();
    })
    .then(instructor => {
        // Убедимся, что у нас есть имя (защита от некорректных данных)
        if (!instructor.name) {
            throw new Error('Некорректные данные инструктора');
        }

        const name = instructor.name;
        localStorage.setItem('instructorName', name);
        localStorage.setItem('instructorId', instructor.id);

        // ✅ НОВОЕ: обновляем имя в верхнем меню
        const nameDisplay = document.getElementById('instructor-name-display');
        if (nameDisplay) {
            nameDisplay.textContent = name;
        }

        // Обновляем интерфейс
        document.getElementById('user-info').innerHTML = `
            <p style="color: black;">Добро пожаловать, <strong>${escapeHtml(name)}</strong></p>
        `;
        document.getElementById('login-link').style.display = 'none';
        document.getElementById('logout-link').style.display = 'block';
        document.querySelector('.login-container').style.display = 'none';
        document.querySelector('.button-container').style.display = 'flex';
        document.getElementById('content-area').style.display = 'block';
    })
    .catch(e => {
        // Очистка при ЛЮБОЙ ошибке авторизации/роли
        localStorage.removeItem('authToken');
        localStorage.removeItem('instructorName');
        localStorage.removeItem('instructorId');
        document.getElementById('user-info').innerHTML = `<p style="color: red;">${escapeHtml(e.message)}</p>`;
    });
}

// Выход
function logout() {
    localStorage.removeItem('authToken');
    localStorage.removeItem('instructorName');
    localStorage.removeItem('instructorId');
    location.reload();
}

//Календарь сессий
function showCalendar() {

    const authToken = localStorage.getItem('authToken');
    const content = document.getElementById('content-area');
    content.innerHTML = '<p>Загрузка календаря...</p>';

    fetch('/api/training-sessions/', {
        headers: getAuthHeaders()
    })
    .then(r => r.json())
    .then(sessions => {
        if (sessions.length === 0) {
            content.innerHTML = '<p>Нет запланированных сессий.</p>';
            return;
        }

        // Сопоставление статусов и их отображения
        const statusLabels = {
            'planned': 'Запланирована',
            'completed': 'Проведена',
            'cancelled': 'Отменена'
        };

        // Цвета для статусов
        const statusColors = {
            'planned': '#ffc107',   // жёлтый
            'completed': '#28a745', // зелёный
            'cancelled': '#dc3545'  // красный
        };

        let html = '<h3>Календарь сессий</h3>';
        html += '<table border="1" cellpadding="8" cellspacing="0" style="width:100%; border-collapse: collapse;">';
        html += '<tr>';
        html += '<th>Сессия</th>';
        html += '<th>Пилот</th>';
        html += '<th>Дата и время</th>';
        html += '<th>Место</th>';
        html += '<th>Статус</th>';  // ✅ Новый заголовок
        html += '</tr>';

        sessions.forEach(s => {
            const date = new Date(s.planned_at).toLocaleString('ru-RU');
            const pilotName = s.pilot ? s.pilot.name : "—";
            const statusLabel = statusLabels[s.status] || s.status;
            const statusColor = statusColors[s.status] || '#6c757d';

            html += `
                <tr>
                    <td>${escapeHtml(s.session.title)}</td>
                    <td>${escapeHtml(pilotName)}</td>
                    <td>${date}</td>
                    <td>${escapeHtml(s.venue || '—')}</td>
                    <td style="text-align: center;">
                        <span style="
                            background-color: ${statusColor};
                            color: white;
                            padding: 4px 8px;
                            border-radius: 4px;
                            font-size: 0.85em;
                            font-weight: bold;">
                            ${statusLabel}
                        </span>
                    </td>
                </tr>
            `;
        });

        html += '</table>';
        content.innerHTML = html;
    })
    .catch(e => {
        content.innerHTML = '<p style="color: red;">Ошибка загрузки календаря.</p>';
        console.error("Ошибка в showCalendar:", e);
    });
}

//Выбор пилота + замечания


function showPilot() {
    const contentArea = document.getElementById('content-area');
    fetch('/pilot-partial/', {
        headers: getAuthHeaders()
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
    })
    .then(html => {
        contentArea.innerHTML = html;
        initPilotSearch(); // ← вызываем инициализацию
    })
    .catch(err => {
        contentArea.innerHTML = '<p style="color: red;">Ошибка загрузки</p>';
        console.error("showPilot error:", err);
    });
}

function initPilotSearch() {
    const input = document.getElementById('pilot-search-input');
    if (!input) return; // если элемента нет — выходим

    const suggestions = document.getElementById('pilot-suggestions');
    let debounceTimer;

    // Удаляем старые обработчики, чтобы не дублировать
    input.removeEventListener('input', input._handler);

    const handler = () => {
        const query = input.value.trim();
        clearTimeout(debounceTimer);

        if (query.length < 2) {
            suggestions.style.display = 'none';
            return;
        }

        debounceTimer = setTimeout(() => {
            fetch(`/pilot-search/?q=${encodeURIComponent(query)}`, {
                headers: getAuthHeaders()
            })
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(pilots => {
                suggestions.innerHTML = '';
                if (pilots.length === 0) {
                    suggestions.innerHTML = '<li style="padding: 6px; color: #888;">Не найдено</li>';
                } else {
                    pilots.forEach(p => {
                        const li = document.createElement('li');
                        li.textContent = p.name;
                        li.style.padding = '6px';
                        li.style.cursor = 'pointer';
                        li.style.borderBottom = '1px solid #eee';
                        li.addEventListener('click', () => {
                            input.value = p.name;
                            suggestions.style.display = 'none';
                            loadPilotData(p.id);
                        });
                        suggestions.appendChild(li);
                    });
                }
                suggestions.style.display = 'block';
            })
            .catch(err => {
                console.error("Ошибка поиска пилотов:", err);
                suggestions.innerHTML = '<li style="padding: 6px; color: red;">Ошибка загрузки</li>';
                suggestions.style.display = 'block';
            });
        }, 300);
    };

    input._handler = handler;
    input.addEventListener('input', handler);

    // Скрытие списка при клике вне
    document.removeEventListener('click', hideSuggestions);
    function hideSuggestions(e) {
        if (!input.contains(e.target) && !suggestions.contains(e.target)) {
            suggestions.style.display = 'none';
        }
    }
    document.addEventListener('click', hideSuggestions);
}

function loadPilotData(pilotId) {
    const contentArea = document.getElementById('content-area');
    fetch(`/pilot-partial/?pilot_id=${encodeURIComponent(pilotId)}`, {
        headers: getAuthHeaders(),
        credentials: 'same-origin'
    })
    .then(response => {
        if (response.status === 403) {
            return response.text().then(text => {
                throw new Error(text || "Доступ запрещён");
            });
        }
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.text();
    })
    .then(html => {
        contentArea.innerHTML = html;
    })
    .catch(err => {
        // Показываем точное сообщение от сервера, если оно есть
        let msg = err.message || "Ошибка загрузки данных пилота";
        if (msg.startsWith("HTTP ")) {
            msg = "Не удалось загрузить данные пилота.";
        }
        contentArea.innerHTML = `<p style="color: red;">${escapeHtml(msg)}</p>`;
        console.error("loadPilotData error:", err);
    });
}
function loadPilotSessions(pilotId) {
    if (!pilotId) {
        showPilot();
        return;
    }
    fetch(`/pilot-partial/?pilot_id=${encodeURIComponent(pilotId)}`, {
        headers: getAuthHeaders()
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
    })
    .then(html => {
        document.getElementById('content-area').innerHTML = html;
    })
    .catch(err => {
        console.error("loadPilotSessions error:", err);
        document.getElementById('content-area').innerHTML = '<p style="color:red">Ошибка загрузки</p>';
    });
}

function loadPrintForm(ratingId, pilotId) {
    if (!pilotId) {
        console.error('Pilot ID is required for print form');
        return;
    }
    const contentArea = document.getElementById('content-area');
    fetch(`/pilot-partial/?pilot_id=${encodeURIComponent(pilotId)}&print_rating=${ratingId}`,{
        headers: getAuthHeaders()
        })
        .then(response => response.text())
        .then(html => {
            contentArea.innerHTML = html;
        })
        .catch(err => {
            contentArea.innerHTML = '<p style="color: red;">Ошибка загрузки формы</p>';
            console.error(err);
        });
}




/**
 * Открывает форму для оценки сессии
 */
function openLegacyIndividualSession() {
    const content = document.getElementById('content-area');
    content.innerHTML = `
        <div class="modal-form">
            <h3>Задание на тренировку</h3>
            <div class="form-group">
                <select id="rating-pilot" onchange="loadAssignedSessions()">
                    <option value="">-- Загрузка пилотов --</option>
                </select>
            </div>
            <div class="form-group">
                <label for="rating-session">Запланированная сессия:</label>
                <select id="rating-session" disabled onchange="loadExercises()">
                    <option value="">-- Сначала выберите пилота --</option>
                </select>
            </div>
            <div id="exercises-container" style="display:none; margin-top: 20px;">
                <h4>Упражнения</h4>
                <div id="exercises-list"></div>
                <div class="form-group">
                    <label for="general_notes">Общие замечания:</label>
                    <textarea id="general_notes" rows="3" style="width:100%; padding:8px;"></textarea>
                </div>
                <button id="save-rating-btn" style="padding:10px 20px; background:#27ae60; color:white; border:none; margin-top: 10px;">
                    Сохранить оценку
                </button>
            </div>
        </div>
    `;

    // 🔽 После вставки HTML — добавляем обработчик
    document.getElementById('save-rating-btn').addEventListener('click', submitRating);

    const authToken = localStorage.getItem('authToken');

    fetch('/api/pilots/', {
        headers: getAuthHeaders()
    })
    .then(r => {
        if (!r.ok) throw new Error('Ошибка загрузки пилотов');
        return r.json();
    })
    .then(pilots => {
        const select = document.getElementById('rating-pilot');
        if (!select) return;
        select.innerHTML = '<option value="">-- Выберите пилота --</option>';
        pilots.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            select.appendChild(opt);
        });
    })
    .catch(e => {
        console.error('Ошибка загрузки пилотов:', e);
        const select = document.getElementById('rating-pilot');
        if (select) select.innerHTML = '<option value="">Ошибка загрузки</option>';
    });
}

// Загружает запланированные сессии (TrainingSession) для выбранного пилота

function loadAssignedSessions() {
    const pilotId = document.getElementById('rating-pilot').value;
    const sessionSelect = document.getElementById('rating-session');
    const exercisesContainer = document.getElementById('exercises-container');

    if (!sessionSelect) return;

    sessionSelect.innerHTML = '<option value="">Загрузка...</option>';
    sessionSelect.disabled = true;
    if (exercisesContainer) exercisesContainer.style.display = 'none';

    if (!pilotId) return;

    const authToken = localStorage.getItem('authToken');

    fetch(`/api/training-sessions/`, {
        method: 'GET',
        headers: {...getAuthHeaders(), 'Content-Type': 'application/json' }
    })
    .then(r => {
        if (!r.ok) throw new Error('Не удалось загрузить сессии');
        return r.json();
    })
    .then(trainingSessions => {
        // Фильтруем: сессия с текущим пилотом и статусом 'planned'
        const filtered = trainingSessions.filter(ts => {
            return ts.pilot && String(ts.pilot.id) === String(pilotId) &&
                   ts.status === 'planned';
        });

        sessionSelect.innerHTML = '<option value="">-- Выберите сессию --</option>';
        if (filtered.length === 0) {
            sessionSelect.innerHTML = '<option value="" disabled>Нет запланированных сессий</option>';
            return;
        }

        filtered.forEach(ts => {
            const opt = document.createElement('option');
            opt.value = ts.session.id;
            opt.textContent = `${ts.session.title} (${new Date(ts.planned_at).toLocaleString('ru-RU')})`;
            opt.dataset.trainingSessionId = ts.id;  // важно: ID самой TrainingSession
            sessionSelect.appendChild(opt);
        });

        sessionSelect.disabled = false;
    })
    .catch(e => {
        console.error('Ошибка загрузки сессий:', e);
        sessionSelect.innerHTML = '<option value="" disabled>Ошибка загрузки</option>';
    });
}





function loadExercises() {
    const sessionId = document.getElementById('rating-session')?.value;
    const container = document.getElementById('exercises-container');
    const list = document.getElementById('exercises-list');

    if (!container || !list) return;

    list.innerHTML = '';
    if (!sessionId) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';
    list.innerHTML = 'Загрузка упражнений...';

    fetch(`/api/session/${sessionId}/exercises/`, {
        headers: getAuthHeaders()
    })
    .then(r => r.json())
    .then(exercises => {
        list.innerHTML = '';
        if (exercises.length === 0) {
            list.innerHTML = '<p>Нет упражнений в этой сессии.</p>';
            return;
        }

        exercises.forEach(ex => {
            const div = document.createElement('div');
            div.className = 'exercise-item';
            div.dataset.assignmentId = ex.id;

            const saved = getSavedExercise(ex.id);
            const minScore = ex.min_score || 3;
            const progressPoint = ex.phase_of_flight || '—';
            const durationTime = ex.duration_minutes || 2;
            const durationMinutes = parseInt(durationTime) || 0;

            let infoBlock = `
                <div style="display: grid; grid-template-columns: auto 1fr; gap: 10px; margin-bottom: 12px; font-size: 0.9em; color: #555;">
                    <div><strong>Пункт прогресса:</strong></div>
                    <div>${escapeHtml(progressPoint)}</div>
                    <div><strong>Минимальная оценка:</strong></div>
                    <div>${escapeHtml(minScore)}</div>
                    <div><strong>Рекомендуемая продолжительность упражнения, мин:</strong></div>
                    <div>
                        ${escapeHtml(durationTime)}
            `;

            if (durationMinutes > 0) {
                infoBlock += `
                        <span id="exercise-timer-${ex.id}" style="margin-left: 8px; color: #d35400; font-weight: bold;">(ждёт запуска)</span>
                    </div>
                </div>
                <button id="start-timer-btn-${ex.id}"
                        data-ex-id="${ex.id}"
                        data-duration="${durationMinutes}"
                        style="margin-top: 2px; padding: 6px 12px; background: #2980b9; color: white; border: none; border-radius: 4px; font-size: 0.9em;">
                    Начать отсчёт
                </button>
                `;
            } else {
                infoBlock += `</div></div>`;
            }

            div.innerHTML = `
                <div style="font-weight: bold; margin-bottom: 4px;">
                    ${escapeHtml(ex.order)}. ${escapeHtml(ex.name)}
                </div>
                ${infoBlock}
                <div style="border: 1px solid #eee; border-radius: 8px; padding: 12px; margin-bottom: 15px; background: #f9f9f9;">
                    <strong style="display: block; margin-bottom: 8px; color: #333;">Оценка по компетенциям EBT</strong>
                    ${generateCompetencyFields(ex.id, saved, ex.required_competencies)}
                </div>

                <div style="margin-bottom: 12px;">
                    <label style="font-weight: bold;">Общая оценка упражнения:</label>
                    <select id="score-${ex.id}" style="width: 100%; padding: 6px; font-size: 18px; margin-top: 4px;">
                        <option value="">Выберите</option>
                        <option value="2" ${saved?.score === 2 ? 'selected' : ''}>2 — Неудовл.</option>
                        <option value="3" ${saved?.score === 3 ? 'selected' : ''}>3 — Удовл.</option>
                        <option value="4" ${saved?.score === 4 ? 'selected' : ''}>4 — Хорошо</option>
                        <option value="5" ${saved?.score === 5 ? 'selected' : ''}>5 — Отлично</option>
                    </select>
                </div>
                <hr style="margin: 15px 0; border: 0.5px solid #eee;">
            `;

            list.appendChild(div);
            setupExerciseEventListeners(ex.id);
        });

        // ✅ ТАЙМЕРЫ — ВНЕ ЦИКЛА, ОДИН РАЗ ПОСЛЕ ВСТАВКИ ВСЕХ УПРАЖНЕНИЙ
        document.querySelectorAll('[id^="start-timer-btn-"]').forEach(btn => {
            if (btn.dataset.attached) return;
            btn.dataset.attached = "true";

            btn.addEventListener('click', function () {
                const exId = this.dataset.exId;
                let totalSeconds = parseInt(this.dataset.duration) * 60;
                const timerEl = document.getElementById(`exercise-timer-${exId}`);

                if (!timerEl) return;

                this.disabled = true;
                this.textContent = 'Идёт отсчёт...';

                const interval = setInterval(() => {
                    totalSeconds--;
                    const mins = Math.floor(totalSeconds / 60);
                    const secs = totalSeconds % 60;
                    timerEl.textContent = `(${mins}:${secs < 10 ? '0' : ''}${secs})`;

                    if (totalSeconds <= 0) {
                        timerEl.style.color = '#e74c3c';
                        timerEl.textContent = '(время вышло!)';
                        clearInterval(interval);
                    }
                }, 1000);
            });
        });

        // Подсветка оценённых упражнений
        updateExerciseItemStyle(exercises.map(e => e.id));

    }) // ← закрытие .then(exercises => { ... })
    .catch(e => {
        list.innerHTML = `<p style="color:red;">Ошибка загрузки упражнений: ${escapeHtml(e.message)}</p>`;
    }); // ← закрытие цепочки промисов
} // ← закрытие функции loadExercises()

// * Генерирует HTML-поля для всех 8 компетенций

function generateCompetencyFields(assignmentId, saved = {}, requiredCompetencies = []) {
    const allCompetencies = [
        { key: 'pro', label: 'PRO — Процедуры' },
        { key: 'com', label: 'COM — Коммуникация' },
        { key: 'fpa', label: 'FPA — Управление траекторией (автоматика)' },
        { key: 'fpm', label: 'FPM — Управление траекторией (ручное)' },
        { key: 'ltw', label: 'LTW — Работа в команде, лидерство' },
        { key: 'psd', label: 'PSD — Решение проблем' },
        { key: 'saw', label: 'SAW — Ситуационная осведомлённость' },
        { key: 'wlm', label: 'WLM — Управление нагрузкой' }
    ];

    // Фильтруем только нужные компетенции
    const competenciesToShow = requiredCompetencies && requiredCompetencies.length > 0
        ? allCompetencies.filter(c => requiredCompetencies.includes(c.key))
        : allCompetencies; // fallback на все, если не указано

    return competenciesToShow.map(comp => {
        const score = saved?.[`${comp.key}_score`] || '0';
        const remarks = saved?.[`${comp.key}_remarks`] || '';
        return `
        <div style="display: grid; grid-template-columns: 180px 120px 1fr; gap: 8px; align-items: start; margin-bottom: 8px;">
            <div style="font-size: 0.9em; font-weight: bold;">${comp.label}</div>
            <select id="${comp.key}_score-${assignmentId}" style="padding: 4px; font-size: 14px;">
                <option value="0" ${score === '0' ? 'selected' : ''}>0 : Не оценивалось</option>
                <option value="1" ${score === '1' ? 'selected' : ''}>1 : Небезопасный</option>
                <option value="2" ${score === '2' ? 'selected' : ''}>2 : Минимально допустимый</option>
                <option value="3" ${score === '3' ? 'selected' : ''}>3 : Стандартный</option>
                <option value="4" ${score === '4' ? 'selected' : ''}>4 : Эффективный</option>
                <option value="5" ${score === '5' ? 'selected' : ''}>5 : Образцовый</option>
            </select>
            <textarea
                id="${comp.key}_remarks-${assignmentId}"
                rows="1"
                style="padding: 4px; font-size: 14px;"
                placeholder="Замечания по ${comp.label.split('—')[0].trim()}">${escapeHtml(remarks)}</textarea>
        </div>
        `;
    }).join('');
}
// Уникальный ключ для localStorage
function getStorageKey(assignmentId) {
    const sessionId = document.getElementById('rating-session')?.value || 'unknown';
    return `exercise_${sessionId}_${assignmentId}`;
}

function saveExerciseLocally(assignmentId, data) {
    try {
        localStorage.setItem(getStorageKey(assignmentId), JSON.stringify(data));
    } catch (e) {
        console.warn('Не удалось сохранить в localStorage:', e);
    }
}

function getSavedExercise(assignmentId) {
    try {
        const item = localStorage.getItem(getStorageKey(assignmentId));
        return item ? JSON.parse(item) : null;
    } catch (e) {
        console.warn('Ошибка чтения из localStorage:', e);
        return null;
    }
}

function setupExerciseEventListeners(assignmentId, requiredCompetencies = []) {
    // Общая оценка
    const scoreEl = document.getElementById(`score-${assignmentId}`);
    if (scoreEl) {
        scoreEl.addEventListener('change', () => {
            collectAndSaveExercise(assignmentId, requiredCompetencies);
            updateExerciseItemStyle([assignmentId]);
        });
    }

    // Компетенции и замечания — только для требуемых
    const competencyKeys = requiredCompetencies.length > 0
        ? requiredCompetencies
        : ['pro', 'com', 'fpa', 'fpm', 'ltw', 'psd', 'saw', 'wlm'];

    competencyKeys.forEach(key => {
        const scoreEl = document.getElementById(`${key}_score-${assignmentId}`);
        const remarksEl = document.getElementById(`${key}_remarks-${assignmentId}`);
        if (scoreEl) scoreEl.addEventListener('change', () => collectAndSaveExercise(assignmentId, requiredCompetencies));
        if (remarksEl) remarksEl.addEventListener('input', () => collectAndSaveExercise(assignmentId, requiredCompetencies));
    });
}

function collectAndSaveExercise(assignmentId, requiredCompetencies = []) {
    const score = document.getElementById(`score-${assignmentId}`)?.value || '';
    const data = { score: score ? parseInt(score, 10) : null };

    const competencyKeys = requiredCompetencies.length > 0
        ? requiredCompetencies
        : ['pro', 'com', 'fpa', 'fpm', 'ltw', 'psd', 'saw', 'wlm'];

    competencyKeys.forEach(key => {
        const s = document.getElementById(`${key}_score-${assignmentId}`)?.value || '0';
        const r = document.getElementById(`${key}_remarks-${assignmentId}`)?.value || '';
        data[`${key}_score`] = parseInt(s, 10);
        data[`${key}_remarks`] = r;
    });

    saveExerciseLocally(assignmentId, data);
}

function updateExerciseItemStyle(assignmentIds) {
    assignmentIds.forEach(id => {
        const el = document.querySelector(`.exercise-item[data-assignment-id="${id}"]`);
        if (!el) return;
        const score = document.getElementById(`score-${id}`)?.value;
        if (score && score !== '') {
            el.style.backgroundColor = '#f0fff0'; // светло-зелёный
            el.style.borderLeft = '4px solid #4CAF50';
        } else {
            el.style.backgroundColor = '';
            el.style.borderLeft = '';
        }
    });
}


function submitRating() {
    console.log("Кнопка 'Сохранить оценку' нажата!");

    const pilotId = document.getElementById('rating-pilot')?.value;
    const sessionSelect = document.getElementById('rating-session');
    const selectedOption = sessionSelect?.selectedOptions[0];
    const generalNotes = (document.getElementById('general_notes')?.value || '').trim();

    const trainingSessionId = selectedOption ? selectedOption.dataset.trainingSessionId : null;

    if (!pilotId || !trainingSessionId) {
        alert('Выберите пилота и сессию');
        return;
    }

    const exercises = [];
    const competencyKeys = ['pro', 'com', 'fpa', 'fpm', 'ltw', 'psd', 'saw', 'wlm'];

    try {
        document.querySelectorAll('.exercise-item').forEach(item => {
            const assignmentId = item.dataset.assignmentId;
            if (!assignmentId) {
                console.error("Нет assignmentId у элемента:", item);
                throw new Error("Некорректное упражнение");
            }

            const scoreEl = document.getElementById(`score-${assignmentId}`);
            const score = scoreEl?.value;
            if (!score) {
                const exerciseName = item.querySelector('div')?.textContent || 'Неизвестное упражнение';
                alert(`Укажите общую оценку для упражнения: ${exerciseName}`);
                throw new Error('Не все оценки заполнены');
            }

            const competencies = {};
            competencyKeys.forEach(key => {
                const scoreEl = document.getElementById(`${key}_score-${assignmentId}`);
                const remarksEl = document.getElementById(`${key}_remarks-${assignmentId}`);

                competencies[`${key}_score`] = parseInt(scoreEl?.value || '0');
                competencies[`${key}_remarks`] = remarksEl?.value || '';
            });

            exercises.push({
                assignment_id: assignmentId,
                score: parseInt(score),
                ...competencies
            });
        });
    } catch (e) {
        console.error("Ошибка при сборе данных:", e);
        return;
    }

    fetch('/api/rating-sessions/', {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
            pilot_id: pilotId,
            session_id: trainingSessionId,
            general_notes: generalNotes, // ← только ручной ввод
            exercises: exercises
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => { throw err; });
        }
        return response.json();
    })
    .then(result => {
        alert('✅ Оценка успешно сохранена!');

        // Очистка
        document.querySelectorAll('.exercise-item').forEach(item => {
            const id = item.dataset.assignmentId;
            localStorage.removeItem(getStorageKey(id));
        });

        if (selectedOption) {
            sessionSelect.removeChild(selectedOption);
        }

        if (sessionSelect.children.length <= 1) {
            sessionSelect.innerHTML = '<option value="" disabled>Нет запланированных сессий</option>';
            document.getElementById('exercises-container').style.display = 'none';
        }

        document.getElementById('general_notes').value = '';
    })
    .catch(error => {
        console.error('Ошибка:', error);
        alert('Ошибка: ' + (error.error || 'Не удалось сохранить оценку.'));
    });
}


// Скрывает все контентные блоки
function hideAllSections() {
    document.querySelectorAll('.content-section').forEach(section => {
        section.style.display = 'none';
    });
}


// Показывает документацию (загружает при первом открытии)
function showDocumentation() {
    hideAllSections(); // предполагается, что эта функция скрывает другие секции

    const content = document.getElementById('content-area');
    if (!content) {
        console.error('Элемент #content-area не найден');
        return;
    }

    // Показываем загрузку
    content.innerHTML = '<h3>Доступные документы:</h3><p>Загрузка...</p>';

    fetch('api/docs/', {
        method: 'GET',
        headers: {
            ...getAuthHeaders(),
        }
    })
    .then(response => {
        if (!response.ok) throw new Error('Сервер вернул ошибку при загрузке документов');
        return response.json();
    })
    .then(data => {
        const files = data.files || [];
        if (files.length > 0) {
        const listHtml = `
            <ul style="list-style: none; padding-left: 0;">
                ${files.map(file => `
                    <li style="list-style: none; margin: 6px 0;">
                        <a href="/media/docs/${encodeURIComponent(file)}"
                           target="_blank"
                           rel="noopener"
                           style="text-decoration: none; color: black; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 36px;">📄</span>
                            <span>${escapeHtml(file)}</span>
                        </a>
                    </li>
                `).join('')}
            </ul>
        `;
            content.innerHTML = `<h3>Доступные документы:</h3>${listHtml}`;
        } else {
            content.innerHTML = '<h3>Доступные документы:</h3><p>Нет доступных документов.</p>';
        }
    })
    .catch(err => {
        console.error('Ошибка загрузки документов:', err);
        content.innerHTML = '<h3>Доступные документы:</h3><p>Не удалось загрузить список документов.</p>';
    });
}

// Вспомогательная функция для экранирования HTML (защита от XSS)
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

//кнопка в начало

document.addEventListener('DOMContentLoaded', function () {
    const backToTopButton = document.getElementById('backToTop');

    if (!backToTopButton) {
        console.warn('Кнопка #backToTop не найдена в DOM');
        return;
    }

    function toggleBackToTopButton() {
        if (window.pageYOffset > 100) {
            backToTopButton.classList.add('show');
        } else {
            backToTopButton.classList.remove('show');
        }
    }

    // Показ/скрытие при прокрутке
    window.addEventListener('scroll', toggleBackToTopButton);

    // Прокрутка наверх по клику
    backToTopButton.addEventListener('click', function () {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });

    // Инициализация (на случай, если страница уже пролистана при загрузке)
    toggleBackToTopButton();
});


async function openSession() {
    const content = document.getElementById('content-area');
    content.textContent = 'Загрузка сессий экипажа…';
    try {
        const {mountCrewSession} = await import('/static/js/crew-session.js');
        await mountCrewSession(content);
    } catch (error) {
        content.textContent = 'Не удалось открыть страницу сессии: ' + error.message;
    }
}
