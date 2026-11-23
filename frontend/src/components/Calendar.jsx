import { useMemo, useState } from "react";
import { date, time, dayKey } from "../lib/data.js";
import { Badge, Empty } from "./Common.jsx";
export default function Calendar({ sessions, onOpen, onRefresh }) {
  const today = dayKey(
    new Date(),
    Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  const [month, setMonth] = useState(() => new Date(today + "T00:00:00Z"));
  const [selected, setSelected] = useState(today);
  const [filter, setFilter] = useState("all");
  const filtered = sessions.filter(
    (s) => filter === "all" || s.status === filter,
  );
  const year = month.getUTCFullYear(),
    m = month.getUTCMonth();
  const days = useMemo(() => {
    const start = new Date(Date.UTC(year, m, 1));
    const offset = (start.getUTCDay() + 6) % 7;
    return Array.from(
      { length: 42 },
      (_, i) => new Date(Date.UTC(year, m, 1 - offset + i)),
    );
  }, [year, m]);
  const selectedSessions = filtered.filter(
    (s) => dayKey(s.planned_at, s.schedule_timezone) === selected,
  );
  const upcoming = filtered
    .filter(
      (s) =>
        s.status === "planned" &&
        dayKey(s.planned_at, s.schedule_timezone) >= today,
    )
    .sort((a, b) => String(a.planned_at).localeCompare(String(b.planned_at)))
    .slice(0, 4);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ПЛАН ПОДГОТОВКИ</span>
          <h1>Календарь сессий</h1>
          <p>Ваши занятия и задания для подготовки заранее.</p>
        </div>
        <div className="button-row">
          <span className="timezone">Время по месту проведения</span>
          <button className="quiet" onClick={onRefresh}>
            Обновить расписание
          </button>
        </div>
      </div>
      <div className="stats">
        <div>
          <span>Предстоящие</span>
          <strong>
            {sessions.filter((s) => s.status === "planned").length}
          </strong>
        </div>
        <div>
          <span>Проведённые</span>
          <strong>
            {sessions.filter((s) => s.status === "completed").length}
          </strong>
        </div>
        <div>
          <span>Всего назначений</span>
          <strong>{sessions.length}</strong>
        </div>
      </div>
      <div className="calendar-layout">
        <section className="panel calendar-panel">
          <div className="panel-heading">
            <h2>
              {new Intl.DateTimeFormat("ru-RU", {
                month: "long",
                year: "numeric",
                timeZone: "UTC",
              }).format(month)}
            </h2>
            <div className="button-row">
              <button
                className="icon-button"
                aria-label="Предыдущий месяц"
                onClick={() => setMonth(new Date(Date.UTC(year, m - 1, 1)))}
              >
                ‹
              </button>
              <button
                className="quiet"
                onClick={() => {
                  setMonth(new Date(today + "T00:00:00Z"));
                  setSelected(today);
                }}
              >
                Сегодня
              </button>
              <button
                className="icon-button"
                aria-label="Следующий месяц"
                onClick={() => setMonth(new Date(Date.UTC(year, m + 1, 1)))}
              >
                ›
              </button>
            </div>
          </div>
          <div className="calendar-week">
            {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
          <div className="calendar-grid">
            {days.map((d) => {
              const key = dayKey(d),
                items = filtered.filter(
                  (s) => dayKey(s.planned_at, s.schedule_timezone) === key,
                );
              return (
                <button
                  key={key}
                  className={`calendar-day ${d.getUTCMonth() !== m ? "muted-day" : ""} ${selected === key ? "selected" : ""} ${today === key ? "today" : ""}`}
                  onClick={() => setSelected(key)}
                  aria-label={`${date(d)}: ${items.length} назначений`}
                  aria-pressed={selected === key}
                >
                  <span>{d.getUTCDate()}</span>
                  {items.length > 0 && (
                    <>
                      <small>
                        {items.length}{" "}
                        {items.length === 1 ? "занятие" : "занятия"}
                      </small>
                      <i />
                    </>
                  )}
                </button>
              );
            })}
          </div>
          <div className="calendar-legend">
            <i /> Назначенные вам занятия
          </div>
        </section>
        <section className="panel day-panel">
          <div className="panel-heading">
            <h2>{date(selected + "T00:00:00Z")}</h2>
          </div>
          <label className="sr-only" htmlFor="status-filter">
            Статус занятий
          </label>
          <select
            id="status-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">Все статусы</option>
            <option value="planned">Запланированные</option>
            <option value="completed">Проведённые</option>
            <option value="cancelled">Отменённые</option>
          </select>
          {selectedSessions.length ? (
            selectedSessions.map((s) => (
              <button
                className="session-card"
                key={s.id}
                onClick={() => onOpen(s.id)}
              >
                <div className="button-row">
                  <b>{time(s.planned_at, s.schedule_timezone)}</b>
                  <Badge status={s.status} />
                </div>
                <h3>
                  {s.is_extra && <span className="badge">EXTRA</span>}{" "}
                  {s.session.title}
                </h3>
                <p>{s.pilot?.name}</p>
                <small>
                  {s.venue || "Место не указано"} <span>↗</span>
                </small>
              </button>
            ))
          ) : (
            <Empty title="Свободный день">На эту дату нет назначений.</Empty>
          )}
        </section>
      </div>
      <section className="panel upcoming">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">ГОТОВЬТЕСЬ ЗАРАНЕЕ</span>
            <h2>Ближайшие занятия</h2>
          </div>
        </div>
        {upcoming.length ? (
          <div className="upcoming-grid">
            {upcoming.map((s) => (
              <button
                className="upcoming-card"
                key={s.id}
                onClick={() => onOpen(s.id)}
              >
                <span>
                  {date(s.planned_at, s.schedule_timezone)} ·{" "}
                  {time(s.planned_at, s.schedule_timezone)}
                </span>
                <h3>
                  {s.is_extra && <span className="badge">EXTRA</span>}{" "}
                  {s.session.title}
                </h3>
                <p>{s.pilot?.name}</p>
                <strong>Открыть задание →</strong>
              </button>
            ))}
          </div>
        ) : (
          <Empty title="Новых занятий пока нет">
            Будущие назначения появятся после составления расписания.
          </Empty>
        )}
      </section>
    </>
  );
}
