import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { Notice } from "./Common.jsx";
import { date, time } from "../lib/data.js";

const labels = {
  create: "Создать",
  update: "Обновить",
  unchanged: "Без изменений",
  skip: "Пропустить отменённую",
  blocked: "Нужна проверка",
};
function NewATCDPilot({ person, start, end, onCreated, onCancel, onBusy }) {
  const [username, setUsername] = useState(`atcd_pilot_${person.id}`);
  const [license, setLicense] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function create(event) {
    event.preventDefault();
    setError("");
    if (password !== repeat) {
      setError("Пароли не совпадают.");
      return;
    }
    setBusy(true);
    onBusy(true);
    try {
      const result = await api("/api/atcd/pilots/create/", {
        method: "POST",
        body: JSON.stringify({
          source_id: person.id,
          start,
          end,
          username,
          license,
          password,
        }),
      });
      setPassword("");
      setRepeat("");
      onCreated(result);
    } catch (e) {
      setError(e.message);
      setPassword("");
      setRepeat("");
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  return (
    <section
      id="atcd-new-pilot"
      className="panel"
      style={{ padding: "20px", margin: "20px 0" }}
    >
      <h3>Создать пилота: {person.name}</h3>
      <p>
        ФИО берём из ATCD. Для SIM Training создаётся отдельная учётная запись
        слушателя.
      </p>
      <form onSubmit={create}>
        <fieldset disabled={busy}>
          <div className="upcoming-grid">
            <label>
              Номер свидетельства пилота
              <input
                value={license}
                onChange={(e) => setLicense(e.target.value)}
                maxLength={20}
                required
              />
            </label>
            <label>
              Логин SIM Training
              <input
                autoComplete="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                maxLength={150}
                required
                autoCapitalize="none"
                spellCheck={false}
              />
            </label>
            <label>
              Пароль SIM Training
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={128}
                required
              />
            </label>
            <label>
              Повторите пароль
              <input
                type="password"
                autoComplete="new-password"
                value={repeat}
                onChange={(e) => setRepeat(e.target.value)}
                maxLength={128}
                required
              />
            </label>
          </div>
          <p>
            Пароль ATCD не переносится. Сохраните новый логин и пароль для
            передачи слушателю. После создания пилот останется в справочнике,
            даже если вы пока не сохраните расписание.
          </p>
          {error && <Notice error>{error}</Notice>}
          <div className="button-row">
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "Создаём…" : "Создать пилота и связать с ATCD"}
            </button>
            <button
              className="quiet"
              type="button"
              onClick={onCancel}
              disabled={busy}
            >
              Отмена
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

export default function ATCDSchedule({ onApplied }) {
  const today = new Date().toISOString().slice(0, 10);
  const [start, setStart] = useState(today),
    [end, setEnd] = useState(today);
  const [newPilot, setNewPilot] = useState(null);
  const [options, setOptions] = useState(null),
    [maps, setMaps] = useState({});
  const [preview, setPreview] = useState(null),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [message, setMessage] = useState("");
  useEffect(() => {
    api("/api/atcd/options/")
      .then((o) => {
        setOptions(o);
        setMaps(o.mappings);
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (newPilot)
      document
        .getElementById("atcd-new-pilot")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [newPilot]);
  function mapping(kind, key, label) {
    return (
      <label>
        {label}
        <select
          value={maps[kind]?.[String(key)] || ""}
          disabled={busy}
          onChange={(e) => {
            const values = { ...maps[kind] };
            if (e.target.value) values[String(key)] = Number(e.target.value);
            else delete values[String(key)];
            setMaps({ ...maps, [kind]: values });
            setPreview((p) => p && { ...p, confirmation: null });
          }}
        >
          <option value="">Выберите соответствие…</option>
          {options[kind].map((o) => (
            <option key={o.id} value={o.id}>
              {o.name || o.title}
            </option>
          ))}
        </select>
      </label>
    );
  }
  async function receive(apply = false) {
    setNewPilot(null);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api("/api/atcd/schedule/", {
        method: "POST",
        body: JSON.stringify({
          start,
          end,
          mappings: maps,
          ...(apply ? { confirmation: preview.confirmation } : {}),
        }),
      });
      if (apply) {
        onApplied?.();
        setPreview(null);
        setMessage(
          `Назначения сохранены: ${result.applied}. Результаты и оценки сохранены без изменений.`,
        );
      } else setPreview(result);
    } catch (e) {
      setError(e.message);
      setPreview((p) => p && { ...p, confirmation: null });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">РАСПИСАНИЕ ПОДГОТОВКИ</span>
          <h1>Получение из ATCD</h1>
          <p>
            Тренажёрные сессии ППП.АУЦ.11 активных групп («Набор» и «Обучение»).
            Проверьте назначения перед сохранением.
          </p>
        </div>
      </div>
      <section className="panel" style={{ padding: "24px" }}>
        <div className="button-row">
          <label>
            С даты
            <input
              type="date"
              value={start}
              disabled={busy}
              onChange={(e) => {
                setNewPilot(null);
                setStart(e.target.value);
                setPreview(null);
              }}
            />
          </label>
          <label>
            По дату
            <input
              type="date"
              value={end}
              disabled={busy}
              onChange={(e) => {
                setNewPilot(null);
                setEnd(e.target.value);
                setPreview(null);
              }}
            />
          </label>
          <button
            className="primary"
            disabled={busy || !options || !start || !end}
            onClick={() => receive()}
          >
            {busy ? "Получаем…" : "Получить расписание из ATCD"}
          </button>
        </div>
        <p>
          Период — до 93 дней. Время показано по месту тренажёра. Если занятие
          исчезло из ATCD, здесь оно автоматически не отменяется.
        </p>
        {error && <Notice error>{error}</Notice>}
        {message && <Notice>{message}</Notice>}
      </section>
      {preview && (
        <section
          className="panel"
          style={{ padding: "24px", marginTop: "20px" }}
        >
          <h2>Предварительная проверка · {preview.rows.length}</h2>
          {!preview.rows.length && (
            <p>За выбранный период тренажёрных назначений не найдено.</p>
          )}
          {newPilot && (
            <NewATCDPilot
              key={newPilot.id}
              person={newPilot}
              start={start}
              end={end}
              onCancel={() => setNewPilot(null)}
              onBusy={setBusy}
              onCreated={(result) => {
                setOptions((o) => ({
                  ...o,
                  pilots: [...o.pilots, result.pilot],
                }));
                setMaps((m) => ({
                  ...m,
                  pilots: {
                    ...m.pilots,
                    [String(result.source_id)]: result.pilot.id,
                  },
                }));
                setPreview((p) => p && { ...p, confirmation: null });
                setNewPilot(null);
                setMessage(
                  `Пилот «${result.pilot.name}» создан. Логин: ${result.username}. Повторите получение расписания для проверки.`,
                );
              }}
            />
          )}
          <Notice>
            Это предварительный просмотр ATCD. Изменения ещё не сохранены в SIM
            Training. Новых назначений:{" "}
            {preview.rows.filter((r) => r.action === "create").length};
            обновлений:{" "}
            {preview.rows.filter((r) => r.action === "update").length}; требуют
            проверки:{" "}
            {preview.rows.filter((r) => r.action === "blocked").length}.
          </Notice>
          {preview.rows.map((item) => {
            const r = item.source;
            return (
              <article
                key={r.id}
                style={{ borderBottom: "1px solid #dce2eb", padding: "20px 0" }}
              >
                <strong>
                  {r.group} · {r.module} · {r.title}
                </strong>
                <p>
                  {date(r.starts_at, r.timezone || "UTC")} ·{" "}
                  {time(r.starts_at, r.timezone || "UTC")} —{" "}
                  {time(r.ends_at, r.timezone || "UTC")} · {r.venue}
                </p>
                <p>
                  {labels[item.action]}
                  {r.status === "cancelled" ? " · Отменено в ATCD" : ""}
                </p>
                {r.status !== "cancelled" && (
                  <div className="upcoming-grid">
                    {r.pilots.map((p) => (
                      <div key={p.id}>
                        {mapping("pilots", p.id, `Пилот ATCD: ${p.name}`)}
                        {!maps.pilots?.[String(p.id)] &&
                          options.can_create_pilot && (
                            <button
                              type="button"
                              className="quiet"
                              disabled={busy}
                              onClick={() => {
                                setError("");
                                setNewPilot(p);
                              }}
                            >
                              Нет в списке? Создать пилота
                            </button>
                          )}
                      </div>
                    ))}
                    <div>
                      {mapping(
                        "instructors",
                        r.instructor.id,
                        `Инструктор ATCD: ${r.instructor.name || "Не назначен"}`,
                      )}
                    </div>
                    <div>
                      {mapping(
                        "templates",
                        r.template_key,
                        `Задание для «${r.title}»`,
                      )}
                    </div>
                  </div>
                )}
                {item.errors.map((e, n) => (
                  <Notice error key={n}>
                    {e}
                  </Notice>
                ))}
              </article>
            );
          })}
          {preview.rows.length > 0 && (
            <>
              {!preview.confirmation && (
                <p>
                  Сопоставления изменены. Нажмите «Получить расписание из ATCD»
                  повторно для проверки.
                </p>
              )}
              <button
                className="primary"
                disabled={busy || !preview.confirmation || !preview.can_apply}
                onClick={() => receive(true)}
              >
                Подтвердить и сохранить назначения
              </button>
              <p>
                Начатые занятия и результаты защищены от изменения. Пилота можно
                создать отдельным действием; шаблоны заданий выбираются из
                существующих.
              </p>
            </>
          )}
        </section>
      )}
    </>
  );
}
