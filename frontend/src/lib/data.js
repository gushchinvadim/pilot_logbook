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
export const date = (value, zone = "UTC") =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: zone,
      }).format(new Date(value))
    : "Дата не назначена";
export const time = (value, zone = "UTC") =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: zone,
      }).format(new Date(value)) +
      " " +
      zone
    : "—";
export const dayKey = (value, zone = "UTC") => {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const get = (type) => parts.find((p) => p.type === type).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
};
export const draftKey = (userId, trainingId) =>
  `sim-training-react:draft:1:${userId}:${trainingId}`;
export const completed = (draft, exercises) =>
  exercises.filter((ex) =>
    [2, 3, 4, 5].includes(Number(draft.exercises?.[ex.id]?.score)),
  ).length;
