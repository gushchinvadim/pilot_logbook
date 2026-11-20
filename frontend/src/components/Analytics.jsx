import { useState } from "react";
import { competencies } from "../lib/data.js";
import { useData, Notice, Empty } from "./Common.jsx";
export default function Analytics({ pilotId }) {
  const { data, error, loading } = useData(
    "/api/results/" + (pilotId ? `?pilot_id=${pilotId}` : ""),
  );
  const [selected, setSelected] = useState("all");
  if (loading) return <Notice>Загрузка аналитики…</Notice>;
  if (error) return <Notice error>{error}</Notice>;
  const pilots = [
    ...new Map((data || []).map((r) => [r.pilot.id, r.pilot])).values(),
  ];
  const results = (data || []).filter(
    (r) => selected === "all" || String(r.pilot.id) === selected,
  );
  const exercises = results.flatMap((r) => r.exercises);
  const avg = exercises.length
    ? (exercises.reduce((a, e) => a + e.score, 0) / exercises.length).toFixed(1)
    : "—";
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ОБЗОР ПОДГОТОВКИ</span>
          <h1>Аналитика</h1>
          <p>Сводка по доступным вам итоговым результатам.</p>
        </div>
        {!pilotId && (
          <label>
            Слушатель
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="all">Все назначенные пилоты</option>
              {pilots.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="stats">
        <div>
          <span>Оценённых занятий</span>
          <strong>{results.length}</strong>
        </div>
        <div>
          <span>Оценок упражнений</span>
          <strong>{exercises.length}</strong>
        </div>
        <div>
          <span>Средняя оценка упражнения</span>
          <strong>
            {avg}
            <small> / 5</small>
          </strong>
        </div>
      </div>
      {!exercises.length ? (
        <Empty title="Пока недостаточно данных">
          Аналитика появится после сохранения итоговых оценок.
        </Empty>
      ) : (
        <div className="analytics-grid">
          <section className="panel">
            <div className="panel-heading">
              <h2>Оценки упражнений</h2>
            </div>
            {[2, 3, 4, 5].map((score) => {
              const n = exercises.filter((e) => e.score === score).length;
              return (
                <div className="distribution" key={score}>
                  <span className={`score score-${score}`}>{score}</span>
                  <div>
                    <div className="bar-track">
                      <div
                        style={{ width: `${(n / exercises.length) * 100}%` }}
                      />
                    </div>
                    <p>
                      {n} из {exercises.length} ·{" "}
                      {Math.round((n / exercises.length) * 100)}%
                    </p>
                  </div>
                </div>
              );
            })}
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Компетенции EBT</h2>
            </div>
            {competencies.map(([key, label]) => {
              const scores = exercises
                .map((e) => e[`${key}_score`])
                .filter((v) => v > 0);
              const mean = scores.length
                ? scores.reduce((a, b) => a + b, 0) / scores.length
                : 0;
              return (
                <div className="ebt-row" key={key}>
                  <div>
                    <b>{key.toUpperCase()}</b>
                    <span>{label}</span>
                    <strong>{scores.length ? mean.toFixed(1) : "—"}</strong>
                  </div>
                  <div className="bar-track">
                    <div style={{ width: `${(mean / 5) * 100}%` }} />
                  </div>
                  <small>
                    {scores.length
                      ? `Оценок: ${scores.length}`
                      : "Не оценивалось"}
                  </small>
                </div>
              );
            })}
            <p className="muted">
              Значения «Не оценивалось» исключены из среднего.
            </p>
          </section>
        </div>
      )}
    </>
  );
}
