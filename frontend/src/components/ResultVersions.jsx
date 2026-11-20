import { useState } from "react";
import { api } from "../lib/api.js";
import { competencies, date, time } from "../lib/data.js";
import { Notice } from "./Common.jsx";

export function VersionStatus({ result }) {
  if (!result.version) return null;
  return (
    <div className="version-status">
      <span className="version-tag">Версия {result.version}</span>
      {result.acknowledgement ? (
        <span className="acknowledged">
          ✓ Ознакомлен: {result.acknowledgement.name} ·{" "}
          {date(result.acknowledgement.acknowledged_at)} ·{" "}
          {time(result.acknowledgement.acknowledged_at)}
        </span>
      ) : (
        <span>Ожидает ознакомления слушателя</span>
      )}
      {!result.is_current && <b>Историческая версия</b>}
    </div>
  );
}

function CorrectionForm({ result, onCancel, onSaved }) {
  const [notes, setNotes] = useState(result.general_notes),
    [reason, setReason] = useState(""),
    [rows, setRows] = useState(() => result.exercises.map((ex) => ({ ...ex }))),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  function change(index, key, value) {
    setRows((items) =>
      items.map((item, i) => (i === index ? { ...item, [key]: value } : item)),
    );
  }
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const next = await api(`/api/results/${result.id}/revisions/`, {
        method: "POST",
        body: JSON.stringify({
          revision_id: result.revision_id,
          content_hash: result.content_hash,
          general_notes: notes,
          reason: reason.trim(),
          exercises: rows,
        }),
      });
      onSaved(next);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="correction-form" onSubmit={save}>
      <h3>Новая версия результата · {result.version + 1}</h3>
      <p>
        Прежние оценки и ознакомление сохранятся. Слушателю нужно будет
        ознакомиться с новой версией.
      </p>
      <fieldset disabled={busy}>
        <label>
          Причина исправления
          <textarea
            required
            rows="2"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <label>
          Общие замечания
          <textarea
            rows="3"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        {rows.map((ex, index) => (
          <details key={ex.assignment_id}>
            <summary>
              {ex.exercise_name} · Оценка {ex.score}
            </summary>
            <label>
              Общая оценка
              <select
                value={ex.score}
                onChange={(e) => change(index, "score", Number(e.target.value))}
              >
                {[2, 3, 4, 5].map((score) => (
                  <option value={score} key={score}>
                    {score}
                  </option>
                ))}
              </select>
            </label>
            {competencies.map(([key, label]) => (
              <div className="competency-fields" key={key}>
                <label>
                  {key.toUpperCase()} · {label}
                  <select
                    value={ex[`${key}_score`] ?? 0}
                    onChange={(e) =>
                      change(index, `${key}_score`, Number(e.target.value))
                    }
                  >
                    <option value="0">Не оценивалось</option>
                    {[1, 2, 3, 4, 5].map((score) => (
                      <option key={score} value={score}>
                        {score}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Замечания · {key.toUpperCase()}
                  <textarea
                    rows="2"
                    value={ex[`${key}_remarks`] || ""}
                    onChange={(e) =>
                      change(index, `${key}_remarks`, e.target.value)
                    }
                  />
                </label>
              </div>
            ))}
          </details>
        ))}
        {error && <Notice error>{error}</Notice>}
        <div className="button-row">
          <button className="primary" disabled={busy || !reason.trim()}>
            {busy ? "Сохраняем…" : `Опубликовать версию ${result.version + 1}`}
          </button>
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={onCancel}
          >
            Отмена
          </button>
        </div>
      </fieldset>
    </form>
  );
}

export function VersionActions({
  result,
  onChanged,
  allowAcknowledge,
  allowRevision,
  renderHistory,
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [editing, setEditing] = useState(false),
    [history, setHistory] = useState(null),
    [historyOpen, setHistoryOpen] = useState(false);
  async function acknowledge() {
    setBusy(true);
    setError("");
    try {
      const key = `sim-training:ack:${result.pilot.id}:${result.revision_id}`;
      let payload;
      try {
        payload = JSON.parse(localStorage.getItem(key));
      } catch {}
      if (!payload || payload.content_hash !== result.content_hash) {
        payload = {
          revision_id: result.revision_id,
          content_hash: result.content_hash,
          event_id: crypto.randomUUID(),
          client_time: new Date().toISOString(),
        };
        localStorage.setItem(key, JSON.stringify(payload));
      }
      const accepted = await api(`/api/results/${result.id}/acknowledge/`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      try {
        localStorage.removeItem(key);
      } catch {}
      if (!accepted.is_current) {
        setError(
          "Подтверждение прежней версии сохранено. Откройте актуальную версию.",
        );
      }
      onChanged(accepted);
      setHistory(null);
      setHistoryOpen(false);
    } catch (e) {
      setError(
        e.message +
          ". Пока сервер не принял подтверждение, результат не считается подтверждённым. Можно повторить отправку.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function toggleHistory() {
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const versions = await api(`/api/results/${result.id}/revisions/`);
      setHistory(versions);
      setHistoryOpen(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  if (!result.version) return null;
  return (
    <div className="version-actions">
      {result.change_reason && (
        <p className="change-reason">
          <b>Причина версии:</b> {result.change_reason}
        </p>
      )}
      {error && <Notice error>{error}</Notice>}
      {allowAcknowledge && result.can_acknowledge && (
        <div className="ack-action">
          <p>
            Подтверждаю ознакомление с оценками и замечаниями в версии{" "}
            {result.version}.
          </p>
          <button className="primary" disabled={busy} onClick={acknowledge}>
            {busy ? "Отправляем…" : "Ознакомлен"}
          </button>
        </div>
      )}
      <div className="button-row">
        {allowRevision && result.can_revise && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => setEditing(!editing)}
          >
            Создать исправленную версию
          </button>
        )}
        <button className="quiet" disabled={busy} onClick={toggleHistory}>
          {historyOpen ? "Скрыть историю" : "История версий"}
        </button>
      </div>
      {editing && (
        <CorrectionForm
          result={result}
          onCancel={() => setEditing(false)}
          onSaved={(next) => {
            onChanged(next);
            setEditing(false);
            setHistory(null);
            setHistoryOpen(false);
          }}
        />
      )}
      {historyOpen && history && (
        <section className="revision-history">
          <h3>Сохранённые версии</h3>
          {history.map((rev) => renderHistory(rev))}
        </section>
      )}
    </div>
  );
}
