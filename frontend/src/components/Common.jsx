import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
export function useData(url, version = 0) {
  const [state, setState] = useState({
    data: null,
    error: "",
    loading: true,
    tag: "",
  });
  useEffect(() => {
    const tag = `${url}:${version}`;
    let active = true;
    setState({ data: null, error: "", loading: true, tag });
    if (!url) {
      setState({ data: null, error: "", loading: false, tag });
      return;
    }
    api(url)
      .then(
        (data) => active && setState({ data, error: "", loading: false, tag }),
      )
      .catch(
        (error) =>
          active &&
          setState({
            data: null,
            error:
              error.status === 401
                ? "Войдите в систему заново."
                : error.message,
            loading: false,
            tag,
          }),
      );
    return () => {
      active = false;
    };
  }, [url, version]);
  return state.tag === `${url}:${version}`
    ? state
    : { data: null, error: "", loading: true };
}
export function Notice({ children, error = false }) {
  return (
    <div
      className={`notice ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function Empty({ title, children }) {
  return (
    <div className="empty">
      <div className="empty-symbol">○</div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Badge({ status }) {
  return (
    <span className={`badge ${status}`}>
      {{
        planned: "Запланирована",
        completed: "Проведена",
        cancelled: "Отменена",
      }[status] || status}
    </span>
  );
}
export function Icon({ name, size = 20 }) {
  const paths = {
    calendar:
      "M8 2v4m8-4v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2ZM7 14h2m3 0h2m3 0h1M7 17h2m3 0h2",
    session: "M8 3h8v4H8zM6 5H4v16h16V5h-2M8 12h8m-8 4h6",
    chart: "M4 3v18h17M8 16v-5m5 5V6m5 10V9",
    exit: "M9 4H4v16h5m5-5 5-3-5-3m-6 3h11",
    plane: "m3 15 7-3V3l2-1 2 10 7 3v2l-7-1v4l2 1H8l2-1v-4l-7 1z",
    menu: "M4 6h16M4 12h16M4 18h16",
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.session} />
    </svg>
  );
}
