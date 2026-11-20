export const competencies = [
  ["pro", "Процедуры"],
  ["com", "Коммуникация"],
  ["fpa", "Автоматика"],
  ["fpm", "Ручное управление"],
  ["ltw", "Работа в команде"],
  ["psd", "Решение проблем"],
  ["saw", "Ситуационная осведомлённость"],
  ["wlm", "Управление нагрузкой"],
];
export const statusLabel = {
  planned: "Запланирована",
  completed: "Проведена",
  cancelled: "Отменена",
};
export const date = (value) =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(value))
    : "Дата не назначена";
export const time = (value) =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      }).format(new Date(value)) + " UTC"
    : "—";
export const dayKey = (value) =>
  value ? new Date(value).toISOString().slice(0, 10) : "";
export const draftKey = (userId, trainingId) =>
  `sim-training-react:draft:1:${userId}:${trainingId}`;
export const completed = (draft, exercises) =>
  exercises.filter((ex) =>
    [2, 3, 4, 5].includes(Number(draft.exercises?.[ex.id]?.score)),
  ).length;
