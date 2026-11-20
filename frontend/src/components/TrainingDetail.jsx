import { date, time } from "../lib/data.js";
import { useData, Notice, Badge } from "./Common.jsx";
import { ResultCard } from "./Results.jsx";
export default function TrainingDetail({ id, isInstructor, onGrade, onBack }) {
  const { data: s, error, loading } = useData(`/api/training-sessions/${id}/`);
  if (loading) return <Notice>Загрузка задания…</Notice>;
  if (error) return <Notice error>{error}</Notice>;
  return (
    <>
      <button className="quiet back" onClick={onBack}>
        ← К календарю
      </button>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ЗАДАНИЕ НА ПОДГОТОВКУ</span>
          <h1>{s.session.title}</h1>
          <p>
            {date(s.planned_at)} · {time(s.planned_at)} ·{" "}
            {s.venue || "Место не указано"}
          </p>
        </div>
        <Badge status={s.status} />
      </div>
      <section className="panel assignment-summary">
        <div>
          <span>Слушатель</span>
          <strong>{s.pilot.name}</strong>
        </div>
        <div>
          <span>Инструктор</span>
          <strong>{s.instructor.name}</strong>
        </div>
        <div>
          <span>Упражнений</span>
          <strong>{s.exercises.length}</strong>
        </div>
      </section>
      {s.session.description && (
        <section className="panel description">
          <h2>Описание занятия</h2>
          <p>{s.session.description}</p>
        </section>
      )}
      {isInstructor && (
        <div className="section-action">
          <p>Оценки и замечания каждого пилота сохраняются отдельно.</p>
          <button
            className="primary"
            onClick={() =>
              onGrade(s.crew_id ? `crew:${s.crew_id}` : `single:${s.id}`)
            }
          >
            Открыть оценивание экипажа →
          </button>
        </div>
      )}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">ДЛЯ ПОДГОТОВКИ ЗАРАНЕЕ</span>
            <h2>Программа тренировки</h2>
          </div>
        </div>
        <div className="assignment-list">
          {s.exercises.map((ex) => (
            <article key={ex.id}>
              <span className="exercise-index">{ex.order ?? "•"}</span>
              <div>
                <h3>{ex.name}</h3>
                <p>
                  {ex.description ||
                    ex.phase_of_flight ||
                    "Описание не указано"}
                </p>
                <small>
                  {ex.duration_minutes ? `${ex.duration_minutes} мин · ` : ""}
                  Минимальная оценка: {ex.min_score}
                </small>
              </div>
            </article>
          ))}
        </div>
      </section>
      {s.result && (
        <>
          <h2 className="section-title">Итоговый результат</h2>
          <ResultCard result={s.result} />
        </>
      )}
    </>
  );
}
