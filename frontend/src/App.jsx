import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./lib/api.js";
import { useData, Icon, Notice } from "./components/Common.jsx";
import Calendar from "./components/Calendar.jsx";
import CrewWorkspace from "./components/CrewWorkspace.jsx";
import TrainingDetail from "./components/TrainingDetail.jsx";
import Results from "./components/Results.jsx";
import Analytics from "./components/Analytics.jsx";
import Documentation from "./components/Documentation.jsx";

const roleLabel = {
  instructor: "Инструктор",
  student: "Слушатель",
  manager: "Ответственный",
};
function Login({ onLogin }) {
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function login(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const { token } = await api(
        "/api/api-token-auth/",
        {
          method: "POST",
          body: JSON.stringify({ username: username.trim(), password }),
        },
        null,
      );
      const user = await api("/api/auth/me/", {}, token);
      if (!user.roles.length)
        throw new Error(
          "У учётной записи не настроен профиль инструктора или слушателя. Обратитесь к ответственному.",
        );
      setToken(token);
      setPassword("");
      onLogin(user);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <div className="login-story">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="plane" size={26} />
          </span>
          <span>
            SIM Training<small>GVE DYNAMICS</small>
          </span>
        </div>
        <div>
          <span className="eyebrow">BOEING 737NG · ПЕРЕУЧИВАНИЕ НА ТИП</span>
          <h1>
            От подготовки
            <br />к уверенной работе
            <br />в экипаже.
          </h1>
          <p>
            Расписание, тренировочные задания и результаты — в одном рабочем
            пространстве.
          </p>
          <div className="story-line">
            <span>01</span> Подготовка <i /> <span>02</span> Тренировка <i />{" "}
            <span>03</span> Разбор
          </div>
        </div>
        <small>Профессиональная подготовка лётных экипажей</small>
      </div>
      <section className="login-form">
        <div>
          <span className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span>
          <h2>Вход в SIM Training</h2>
          <p>
            Используйте учётную запись, выданную ответственным за подготовку.
          </p>
          <form onSubmit={login}>
            <fieldset disabled={busy}>
              <label>
                Логин
                <input
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoCapitalize="none"
                  spellCheck={false}
                />
              </label>
              <label>
                Пароль
                <input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </label>
              <button
                className="primary"
                disabled={busy || !username.trim() || !password}
              >
                {busy ? "Входим…" : "Войти в личный кабинет →"}
              </button>
            </fieldset>
          </form>
          {error && <Notice error>{error}</Notice>}
          <div className="login-note">
            <Icon name="session" />
            <p>
              Доступны только назначенные вам занятия и разрешённые результаты.
            </p>
          </div>
        </div>
        <small>SIM Training · GVE Dynamics</small>
      </section>
    </main>
  );
}
function Portal({ user, onLogout }) {
  const [role, setRole] = useState(user.roles[0]),
    [view, setView] = useState("calendar"),
    [trainingId, setTrainingId] = useState(null),
    [crewKey, setCrewKey] = useState(""),
    [menu, setMenu] = useState(false),
    [version, setVersion] = useState(0);
  const { data, error, loading } = useData(
    "/api/my-training-sessions/",
    version,
  );
  const isInstructor = role === "instructor";
  const sessions = (data || []).filter((s) =>
    role === "student"
      ? s.pilot?.id === user.pilot_id
      : role === "instructor"
        ? s.instructor_id === user.instructor_id
        : true,
  );
  const calendarSessions =
    role === "instructor"
      ? [
          ...sessions
            .reduce((groups, s) => {
              const key = s.crew_id ? `crew:${s.crew_id}` : `single:${s.id}`;
              if (!groups.has(key))
                groups.set(key, {
                  ...s,
                  pilot: { ...s.pilot },
                  participants: [s],
                });
              else {
                const g = groups.get(key);
                g.participants.push(s);
                g.pilot.name = g.participants
                  .map((p) => p.pilot.name)
                  .join(" / ");
                g.status = g.participants.some((p) => p.status === "planned")
                  ? "planned"
                  : g.participants.every((p) => p.status === "completed")
                    ? "completed"
                    : "cancelled";
              }
              return groups;
            }, new Map())
            .values(),
        ]
      : sessions;
  const nav = [
    ["calendar", "calendar", "Календарь"],
    ...(isInstructor ? [["crew", "session", "Оценивание экипажа"]] : []),
    ["results", "session", "Результаты занятий"],
    ["analytics", "chart", "Аналитика"],
    ["documentation", "document", "Документация"],
  ];
  const title = nav.find((n) => n[0] === view)?.[2] || "Задание на тренировку";
  function navigate(next) {
    setView(next);
    setMenu(false);
  }
  return (
    <div className="app-shell">
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("calendar");
          }}
        >
          <span className="brand-mark">
            <Icon name="plane" size={25} />
          </span>
          <span>
            SIM Training<small>GVE DYNAMICS</small>
          </span>
        </a>
        <div className="program">
          <span>ПРОГРАММА ПОДГОТОВКИ</span>
          <strong>Boeing 737NG</strong>
          <small>Переучивание на тип ВС</small>
        </div>
        <span className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</span>
        <nav>
          {nav.map(([key, icon, label]) => (
            <button
              className={view === key ? "active" : ""}
              key={key}
              onClick={() => navigate(key)}
            >
              <Icon name={icon} />
              {label}
              {view === key && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="connection-dot" /> Подключение через сервер
          <small>Индивидуальные результаты подготовки</small>
        </div>
      </aside>
      {menu && (
        <button
          className="menu-overlay"
          aria-label="Закрыть меню"
          onClick={() => setMenu(false)}
        />
      )}
      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="menu-toggle icon-button"
              aria-label="Открыть меню"
              onClick={() => setMenu(!menu)}
            >
              <Icon name="menu" />
            </button>
            <span>Подготовка экипажей</span>
            <b>/</b>
            <strong>{title}</strong>
          </div>
          <div className="user-menu">
            {user.roles.length > 1 ? (
              <label className="role-select">
                <span className="sr-only">Рабочая роль</span>
                <select
                  value={role}
                  onChange={(e) => {
                    setRole(e.target.value);
                    setView("calendar");
                  }}
                >
                  {user.roles.map((r) => (
                    <option value={r} key={r}>
                      {roleLabel[r]}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <span className="role-chip">{roleLabel[role]}</span>
            )}
            <span className="user-avatar">
              {user.name
                .split(" ")
                .slice(0, 2)
                .map((s) => s[0])
                .join("")}
            </span>
            <span className="user-name">{user.name}</span>
            <button
              className="icon-button"
              title="Выйти"
              aria-label="Выйти"
              onClick={onLogout}
            >
              <Icon name="exit" />
            </button>
          </div>
        </header>
        <main className="page-content">
          {view === "calendar" ? (
            loading ? (
              <Notice>Загрузка расписания…</Notice>
            ) : error ? (
              <Notice error>
                {error}
                <button
                  className="quiet"
                  onClick={() => setVersion((v) => v + 1)}
                >
                  Повторить
                </button>
              </Notice>
            ) : (
              <Calendar
                sessions={calendarSessions}
                onOpen={(id) => {
                  setTrainingId(id);
                  setView("detail");
                }}
              />
            )
          ) : view === "crew" ? (
            <CrewWorkspace key={crewKey} initialKey={crewKey} user={user} />
          ) : view === "detail" ? (
            <TrainingDetail
              id={trainingId}
              isInstructor={isInstructor}
              onBack={() => navigate("calendar")}
              onGrade={(key) => {
                setCrewKey(key);
                navigate("crew");
              }}
            />
          ) : view === "documentation" ? (
            <Documentation />
          ) : view === "results" ? (
            <Results
              pilotId={role === "student" ? user.pilot_id : null}
              allowAcknowledge={role === "student"}
              allowRevision={role === "manager"}
            />
          ) : (
            <Analytics pilotId={role === "student" ? user.pilot_id : null} />
          )}
        </main>
        <footer className="app-footer">
          SIM Training <span>GVE Dynamics · Подготовка Boeing 737NG</span>
        </footer>
      </div>
    </div>
  );
}
export default function App() {
  const [user, setUser] = useState(null),
    [checking, setChecking] = useState(!!getToken());
  useEffect(() => {
    if (!getToken()) return;
    api("/api/auth/me/")
      .then((u) => {
        if (!u.roles.length) throw new Error("Нет профиля");
        setUser(u);
      })
      .catch(() => setToken(null))
      .finally(() => setChecking(false));
  }, []);
  if (checking)
    return (
      <main className="startup">
        <Icon name="plane" size={40} />
        <p>Открываем SIM Training…</p>
      </main>
    );
  return user ? (
    <Portal
      user={user}
      onLogout={() => {
        setToken(null);
        setUser(null);
      }}
    />
  ) : (
    <Login onLogin={setUser} />
  );
}
