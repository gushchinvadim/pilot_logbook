import { useState } from "react";
import { api } from "../lib/api.js";
import { useData, Icon, Notice, Empty } from "./Common.jsx";

export default function Documentation() {
  const [version, setVersion] = useState(0);
  const [search, setSearch] = useState("");
  const [opening, setOpening] = useState("");
  const [openError, setOpenError] = useState("");
  const { data, error, loading } = useData("/api/docs/", version);
  const files = (data?.files || []).filter((name) =>
    name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );

  async function openDocument(filename) {
    const win = window.open("", "_blank");
    if (!win) {
      setOpenError("Разрешите открытие новой вкладки для просмотра PDF.");
      return;
    }
    win.opener = null;
    setOpening(filename);
    setOpenError("");
    try {
      const { url } = await api("/api/docs/open/", {
        method: "POST",
        body: JSON.stringify({ filename }),
      });
      const target = new URL(url, window.location.href);
      if (target.origin !== window.location.origin || !target.pathname.startsWith("/api/docs/file/")) {
        throw new Error("Не удалось получить адрес документа.");
      }
      if (!win.closed) win.location.replace(target.href);
    } catch (error) {
      win.close();
      setOpenError(error.message || "Не удалось открыть документ.");
    } finally {
      setOpening("");
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">МАТЕРИАЛЫ ДЛЯ ПОДГОТОВКИ</span>
          <h1>Документация</h1>
          <p>Справочники и учебные материалы для инструкторов и слушателей.</p>
        </div>
        <button className="secondary" disabled={loading || Boolean(opening)} onClick={() => setVersion((v) => v + 1)}>
          Обновить список
        </button>
      </div>
      {openError && <Notice error>{openError}</Notice>}
      {loading ? <Notice>Загрузка документов…</Notice> : error ? <Notice error>{error}</Notice> : !data?.files?.length ? (
        <Empty title="Документов пока нет">Загруженные администратором PDF появятся здесь.</Empty>
      ) : (
        <section className="panel documentation-panel">
          <div className="panel-heading">
            <h2>Доступные документы · {data.files.length}</h2>
            <label>Поиск по названию
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Например, FCOM или QRH" />
            </label>
          </div>
          {!files.length ? <Empty title="Документы не найдены">Попробуйте изменить поисковый запрос.</Empty> : (
            <ul className="reference-documents">
              {files.map((filename) => <li key={filename}>
                <button className="reference-document" disabled={Boolean(opening)} onClick={() => openDocument(filename)}
                  aria-label={`Открыть PDF в новой вкладке: ${filename}`}>
                  <Icon name="document" size={26} />
                  <span>{filename}</span>
                  <small>{opening === filename ? "Открываем…" : "PDF ↗"}</small>
                </button>
              </li>)}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
