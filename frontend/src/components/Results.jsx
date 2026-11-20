import { useEffect, useState } from "react";
import { competencies, date, time } from "../lib/data.js";
import { printResult } from "../lib/api.js";
import { useData, Notice, Empty } from "./Common.jsx";
import { VersionActions, VersionStatus } from "./ResultVersions.jsx";
export function ResultCard({
  result: initialResult,
  compact = false,
  allowAcknowledge = false,
  allowRevision = false,
  historyEntry = false,
}) {
  const [result, setResult] = useState(initialResult);
  useEffect(() => setResult(initialResult), [initialResult]);
  const [error, setError] = useState("");
  return (
    <article className="result-card">
      <div className="result-heading">
        <div>
          <span className="eyebrow">
            {date(result.created_at)} · {time(result.created_at)}
          </span>
          <h3>{result.session.title}</h3>
          <p>
            {result.pilot.name} · Инструктор: {result.instructor.name}
          </p>
        </div>
        <button
          className="secondary"
          onClick={() => {
            setError("");
            printResult(result.id, result.revision_id).catch((e) =>
              setError(e.message),
            );
          }}
        >
          Распечатать
        </button>
      </div>
      <VersionStatus result={result} />
      {error && <Notice error>{error}</Notice>}
      {result.general_notes && (
        <div className="remark">
          <b>Общие замечания</b>
          <p>{result.general_notes}</p>
        </div>
      )}
      <details open={!compact}>
        <summary>
          Оценки и замечания по упражнениям · {result.exercises.length}
        </summary>
        <div className="results-exercises">
          {result.exercises.map((ex) => (
            <section className="result-exercise" key={ex.assignment_id}>
              <div>
                <h4>{ex.exercise_name}</h4>
                <span className={`score score-${ex.score}`}>{ex.score}</span>
              </div>
              {competencies
                .filter(
                  ([key]) => ex[`${key}_score`] > 0 || ex[`${key}_remarks`],
                )
                .map(([key, label]) => (
                  <div className="competency-result" key={key}>
                    <span>
                      <b>{key.toUpperCase()}</b> · {label}{" "}
                      {ex[`${key}_score`] > 0 && (
                        <strong>{ex[`${key}_score`]}</strong>
                      )}
                    </span>
                    {ex[`${key}_remarks`] && <p>{ex[`${key}_remarks`]}</p>}
                  </div>
                ))}
            </section>
          ))}
        </div>
      </details>
      {!historyEntry && (
        <VersionActions
          result={result}
          onChanged={setResult}
          allowAcknowledge={allowAcknowledge}
          allowRevision={allowRevision}
          renderHistory={(revision) => (
            <ResultCard
              key={revision.revision_id}
              result={revision}
              compact
              historyEntry
            />
          )}
        />
      )}
    </article>
  );
}
export function History({ pilotId, trainingId }) {
  const { data, error, loading } = useData(`/api/results/?pilot_id=${pilotId}`);
  const previous = (data || []).filter((r) => r.training_id !== trainingId);
  return (
    <aside className="history-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">ПРЕЕМСТВЕННОСТЬ ПОДГОТОВКИ</span>
          <h2>Замечания предыдущих занятий</h2>
          <p>
            Для проверки исправлений. Предыдущие результаты доступны только для
            чтения.
          </p>
        </div>
      </div>
      {loading ? (
        <Notice>Загрузка истории…</Notice>
      ) : error ? (
        <Notice error>{error}</Notice>
      ) : previous.length ? (
        previous.map((r) => <ResultCard key={r.id} result={r} compact />)
      ) : (
        <Empty title="Предыдущих результатов нет">
          История появится после сохранения занятий инструктором.
        </Empty>
      )}
    </aside>
  );
}
export default function Results({
  pilotId,
  allowAcknowledge = false,
  allowRevision = false,
}) {
  const { data, error, loading } = useData(
    "/api/results/" + (pilotId ? `?pilot_id=${pilotId}` : ""),
  );
  const [query, setQuery] = useState("");
  const filtered = (data || []).filter((r) =>
    `${r.pilot.name} ${r.session.title} ${r.instructor.name} ${r.general_notes}`
      .toLocaleLowerCase("ru")
      .includes(query.toLocaleLowerCase("ru")),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ИСТОРИЯ ПОДГОТОВКИ</span>
          <h1>Результаты занятий</h1>
          <p>Итоговые оценки, замечания и выполненные задания для печати.</p>
        </div>
      </div>
      <label className="search">
        <span className="sr-only">Поиск по результатам</span>
        <input
          placeholder="Найти задание, пилота или инструктора"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {loading ? (
        <Notice>Загрузка результатов…</Notice>
      ) : error ? (
        <Notice error>{error}</Notice>
      ) : filtered.length ? (
        filtered.map((r) => (
          <ResultCard
            key={r.id}
            result={r}
            compact
            allowAcknowledge={allowAcknowledge}
            allowRevision={allowRevision}
          />
        ))
      ) : (
        <Empty title="Результатов пока нет">
          Оценки появятся после итогового сохранения инструктором и подключения
          к серверу.
        </Empty>
      )}
    </>
  );
}
