import { useState, useRef, useEffect } from "react";
import { api } from "../lib/api.js";
import { competencies, date, time, draftKey, completed } from "../lib/data.js";
import { Notice, Empty, useData } from "./Common.jsx";
import { History, ResultCard } from "./Results.jsx";

function Pairing({ sessions, onPaired, disabled }) {
  const [first, setFirst] = useState(""),
    [second, setSecond] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const options = sessions.filter(
    (s) => !s.crew_id && s.participants.length === 1,
  );
  async function pair() {
    setError("");
    if (!first || !second || first === second) {
      setError("Выберите две разные записи.");
      return;
    }
    const labels = [first, second]
      .map((id) => options.find((s) => String(s.participants[0].id) === id))
      .filter(Boolean)
      .map(
        (s) =>
          `${s.participants[0].pilot.name} · ${s.session.title} · ${date(s.participants[0].planned_at)}`,
      );
    if (
      !window.confirm(
        `Связать эти две записи в экипаж?\n${labels.join("\n")}\nИндивидуальные результаты сохранятся.`,
      )
    )
      return;
    setBusy(true);
    try {
      const r = await api("/api/crew-sessions/", {
        method: "POST",
        body: JSON.stringify({ training_ids: [Number(first), Number(second)] }),
      });
      onPaired(`crew:${r.crew_id}`);
      setFirst("");
      setSecond("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="panel pairing">
      <summary>Связать две существующие записи в экипаж</summary>
      <p>
        Выберите записи двух пилотов с одним заданием и инструктором. Даты и
        результаты останутся прежними.
      </p>
      <div className="pairing-fields">
        {[
          [first, setFirst, "Первый пилот"],
          [second, setSecond, "Второй пилот"],
        ].map(([value, set, label]) => (
          <label key={label}>
            {label}
            <select
              value={value}
              onChange={(e) => set(e.target.value)}
              disabled={disabled || busy}
            >
              <option value="">Выберите запись</option>
              {options.map((s) => (
                <option key={s.key} value={s.participants[0].id}>
                  {s.participants[0].pilot.name} · {s.session.title} ·{" "}
                  {date(s.participants[0].planned_at)}
                </option>
              ))}
            </select>
          </label>
        ))}
        <button
          className="secondary"
          disabled={busy || disabled}
          onClick={pair}
        >
          {busy ? "Объединяем…" : "Объединить записи"}
        </button>
      </div>
      {error && <Notice error>{error}</Notice>}
    </details>
  );
}

function GradeSelect({
  label,
  value,
  onChange,
  competency = false,
  disabled = false,
}) {
  return (
    <label>
      {label}
      <select
        value={value ?? (competency ? 0 : "")}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
        disabled={disabled}
      >
        {competency ? (
          <>
            <option value="0">Не оценивалось</option>
            <option value="1">1 — Небезопасный</option>
          </>
        ) : (
          <option value="">Выберите оценку</option>
        )}
        <option value="2">
          2 — {competency ? "Минимально допустимый" : "Неудовлетворительно"}
        </option>
        <option value="3">
          3 — {competency ? "Стандартный" : "Удовлетворительно"}
        </option>
        <option value="4">4 — {competency ? "Эффективный" : "Хорошо"}</option>
        <option value="5">5 — {competency ? "Образцовый" : "Отлично"}</option>
      </select>
    </label>
  );
}

function ExerciseTimer({ minutes, end, onStart }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!end) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [end]);
  const seconds = end ? Math.max(0, Math.ceil((end - now) / 1000)) : null;
  return (
    <div className="exercise-timer">
      <span>
        {seconds === null
          ? `Рекомендуемое время: ${minutes} мин`
          : `Осталось: ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}
      </span>
      <button
        className="quiet"
        type="button"
        onClick={() => {
          setNow(Date.now());
          onStart(Date.now() + Number(minutes) * 60000);
        }}
      >
        {end ? "Начать заново" : "Начать отсчёт"}
      </button>
    </div>
  );
}

function DraftEditor({
  user,
  person,
  group,
  exercises,
  onSaved,
  onProgress,
  onBusy,
  leaveGuard,
}) {
  const key = draftKey(user.id, person.id);
  const [initial] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      const d = raw ? JSON.parse(raw) : null;
      if (
        d &&
        (d.pilot_id !== person.pilot.id ||
          d.session_id !== group.session.id ||
          !d.exercises)
      )
        throw new Error("Несовместимый черновик");
      return {
        draft: d || {
          pilot_id: person.pilot.id,
          session_id: group.session.id,
          exercises: {},
          general_notes: "",
        },
        error: "",
      };
    } catch {
      return {
        draft: null,
        error:
          "Не удалось прочитать черновик. Он сохранён в хранилище; сначала нужно устранить ошибку.",
      };
    }
  });
  const [draft, setDraft] = useState(initial.draft),
    [error, setError] = useState(initial.error),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false);
  const failed = useRef(!!initial.error),
    form = useRef(null),
    latest = useRef(initial.draft);
  useEffect(() => {
    leaveGuard.current = () => !failed.current;
    return () => {
      leaveGuard.current = () => true;
    };
  }, [leaveGuard]);
  useEffect(() => {
    if (form.current) form.current.scrollTop = draft?.scroll || 0;
  }, []);
  function store(next) {
    latest.current = next;
    setDraft(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
      failed.current = false;
      setError("");
      setSaved(true);
      onProgress(completed(next, exercises));
    } catch {
      failed.current = true;
      setError(
        "Не удалось сохранить черновик на устройстве. Не переключайте пилота и не закрывайте страницу.",
      );
    }
  }
  function exercise(id, field, value) {
    store({
      ...latest.current,
      exercises: {
        ...latest.current.exercises,
        [id]: { ...latest.current.exercises[id], [field]: value },
      },
    });
  }
  async function publish() {
    if (!draft || failed.current) return;
    if (!exercises.length || completed(draft, exercises) !== exercises.length) {
      setError("Заполните общие оценки всех упражнений.");
      return;
    }
    if (
      !window.confirm(
        `Сохранить итоговые оценки пилота «${person.pilot.name}»? Слушатель получит их через сервер.`,
      )
    )
      return;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      await api("/api/rating-sessions/", {
        method: "POST",
        body: JSON.stringify({
          pilot_id: person.pilot.id,
          session_id: person.id,
          general_notes: draft.general_notes,
          exercises: exercises.map((ex) => ({
            ...draft.exercises[ex.id],
            assignment_id: ex.id,
          })),
        }),
      });
      try {
        localStorage.removeItem(key);
      } catch {}
      onSaved();
    } catch (e) {
      setError(e.message + ". Черновик остался на устройстве.");
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  if (!draft) return <Notice error>{error}</Notice>;
  return (
    <div className="grading-editor">
      <div className="draft-bar">
        <span className="status-dot" />
        {saved ? "Черновик сохранён на устройстве" : "Индивидуальный черновик"}
        <span>
          {completed(draft, exercises)} / {exercises.length}
        </span>
      </div>
      {error && <Notice error>{error}</Notice>}
      <fieldset
        disabled={busy}
        ref={form}
        className="grading-fields"
        onScroll={(e) => {
          latest.current.scroll = e.currentTarget.scrollTop;
          try {
            localStorage.setItem(key, JSON.stringify(latest.current));
          } catch {
            failed.current = true;
            setError("Не удалось сохранить положение и черновик.");
          }
        }}
      >
        {exercises.map((ex) => (
          <section className="exercise-card" key={ex.id}>
            <div className="exercise-title">
              <span className="exercise-index">{ex.order ?? "•"}</span>
              <div>
                <h3>{ex.name}</h3>
                <p>
                  {ex.phase_of_flight || "Упражнение"} · Минимальная оценка{" "}
                  {ex.min_score}
                </p>
              </div>
            </div>
            {ex.description && (
              <p className="exercise-description">{ex.description}</p>
            )}
            {Number(ex.duration_minutes) > 0 && (
              <ExerciseTimer
                minutes={ex.duration_minutes}
                end={draft.timerEnds?.[ex.id]}
                onStart={(end) =>
                  store({
                    ...latest.current,
                    timerEnds: { ...latest.current.timerEnds, [ex.id]: end },
                  })
                }
              />
            )}
            <GradeSelect
              label="Общая оценка упражнения"
              value={draft.exercises[ex.id]?.score}
              onChange={(v) => exercise(ex.id, "score", v)}
            />
            <details
              open={!!draft.expanded?.[ex.id]}
              onToggle={(e) => {
                if (e.target.open !== !!latest.current.expanded?.[ex.id])
                  store({
                    ...latest.current,
                    expanded: {
                      ...latest.current.expanded,
                      [ex.id]: e.target.open,
                    },
                  });
              }}
            >
              <summary>Компетенции и замечания</summary>
              {competencies
                .filter(
                  ([k]) =>
                    !ex.required_competencies.length ||
                    ex.required_competencies.includes(k),
                )
                .map(([k, label]) => (
                  <div className="competency-fields" key={k}>
                    <GradeSelect
                      competency
                      label={`${k.toUpperCase()} · ${label}`}
                      value={draft.exercises[ex.id]?.[`${k}_score`]}
                      onChange={(v) => exercise(ex.id, `${k}_score`, v)}
                    />
                    <label>
                      Замечания · {k.toUpperCase()}
                      <textarea
                        rows="2"
                        value={draft.exercises[ex.id]?.[`${k}_remarks`] || ""}
                        onChange={(e) =>
                          exercise(ex.id, `${k}_remarks`, e.target.value)
                        }
                      />
                    </label>
                  </div>
                ))}
            </details>
          </section>
        ))}
        <label className="general-notes">
          Общие замечания по этому пилоту
          <textarea
            rows="4"
            value={draft.general_notes}
            onChange={(e) =>
              store({ ...latest.current, general_notes: e.target.value })
            }
          />
        </label>
      </fieldset>
      <div className="publish-bar">
        <p>Сохранение одного пилота не завершает второго.</p>
        <button
          className="primary"
          disabled={busy || !!initial.error}
          onClick={publish}
        >
          {busy ? "Сохраняем…" : "Сохранить итоговые оценки"}
        </button>
      </div>
    </div>
  );
}

function GroupEditor({
  user,
  group,
  version,
  onSaved,
  busy,
  onBusy,
  leaveGuard,
}) {
  const [pilotId, setPilotId] = useState(
    group.participants.find((p) => !p.result)?.id || group.participants[0].id,
  );
  const [counts, setCounts] = useState({});
  const person =
    group.participants.find((p) => p.id === pilotId) || group.participants[0];
  const {
    data: detail,
    error,
    loading,
  } = useData(`/api/training-sessions/${person.id}/`, version);
  return (
    <>
      <section className="crew-header">
        <div>
          <span className="eyebrow">
            {group.crew_id ? "ЭКИПАЖНАЯ СЕССИЯ" : "ИНДИВИДУАЛЬНАЯ ЗАПИСЬ"}
          </span>
          <h2>{group.session.title}</h2>
          <p>
            {date(person.planned_at)} · {time(person.planned_at)} ·{" "}
            {person.venue}
          </p>
        </div>
      </section>
      <div className="pilot-tabs" role="group" aria-label="Выбор пилота">
        {group.participants.map((p) => (
          <button
            key={p.id}
            aria-pressed={p.id === person.id}
            disabled={busy}
            onClick={() => {
              if (leaveGuard.current()) setPilotId(p.id);
            }}
          >
            <span className="avatar">
              {p.pilot.name
                .split(" ")
                .slice(0, 2)
                .map((w) => w[0])
                .join("")}
            </span>
            <span>
              <strong>{p.pilot.name}</strong>
              <small>
                {p.result
                  ? "Итоговые оценки сохранены"
                  : counts[p.id] !== undefined
                    ? `Заполнено: ${counts[p.id]} / ${detail?.exercises.length ?? "—"}`
                    : "Индивидуальный черновик"}
              </small>
            </span>
          </button>
        ))}
      </div>
      {loading ? (
        <Notice>Загрузка задания пилота…</Notice>
      ) : error ? (
        <Notice error>{error}</Notice>
      ) : (
        detail && (
          <div className="grading-layout">
            <div>
              {detail.result ? (
                <ResultCard result={detail.result} />
              ) : person.status === "planned" ? (
                <DraftEditor
                  key={person.id}
                  user={user}
                  person={person}
                  group={group}
                  exercises={detail.exercises}
                  onSaved={onSaved}
                  onBusy={onBusy}
                  leaveGuard={leaveGuard}
                  onProgress={(n) =>
                    setCounts((c) => ({ ...c, [person.id]: n }))
                  }
                />
              ) : (
                <Empty title="Занятие закрыто">
                  Редактирование результатов недоступно.
                </Empty>
              )}
            </div>
            <History pilotId={person.pilot.id} trainingId={person.id} />
          </div>
        )
      )}
    </>
  );
}
export default function CrewWorkspace({ user, initialKey }) {
  const [version, setVersion] = useState(0),
    [selected, setSelected] = useState(initialKey || ""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const leaveGuard = useRef(() => true);
  const { data, error, loading } = useData("/api/crew-sessions/", version);
  const sessions = data?.sessions || [];
  const group = sessions.find((s) => s.key === selected);
  const refresh = () => {
    setMessage("Итоговые оценки сохранены на сервере.");
    setVersion((v) => v + 1);
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">РАБОЧЕЕ МЕСТО ИНСТРУКТОРА</span>
          <h1>Оценивание экипажа</h1>
          <p>Два пилота, отдельные результаты и история предыдущих занятий.</p>
        </div>
      </div>
      {message && <Notice>{message}</Notice>}
      {error ? (
        <Notice error>{error}</Notice>
      ) : loading ? (
        <Notice>Загрузка своих назначений…</Notice>
      ) : (
        <>
          <label className="session-selector">
            Сессия и экипаж
            <select
              value={selected}
              disabled={busy}
              onChange={(e) => {
                if (leaveGuard.current()) {
                  setSelected(e.target.value);
                  setMessage("");
                }
              }}
            >
              <option value="">Выберите сессию</option>
              {sessions.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.session.title} ·{" "}
                  {s.participants.map((p) => p.pilot.name).join(" / ")} ·{" "}
                  {date(s.participants[0].planned_at)}
                </option>
              ))}
            </select>
          </label>
          <Pairing
            sessions={sessions}
            disabled={busy}
            onPaired={(key) => {
              setSelected(key);
              setMessage(
                "Записи объединены. Индивидуальные результаты сохранены.",
              );
              setVersion((v) => v + 1);
            }}
          />
          {group ? (
            <GroupEditor
              key={group.key}
              group={group}
              user={user}
              version={version}
              busy={busy}
              onBusy={setBusy}
              leaveGuard={leaveGuard}
              onSaved={refresh}
            />
          ) : (
            <Empty title="Выберите тренажёрную сессию">
              Можно открыть отдельное назначение или связать две записи экипажа.
            </Empty>
          )}
        </>
      )}
    </>
  );
}
