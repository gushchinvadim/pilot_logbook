import { openPrintDocument } from "./printDocument.js";

const KEY = "sim-training-session";
export const getToken = () => sessionStorage.getItem(KEY);
export const setToken = (value) =>
  value ? sessionStorage.setItem(KEY, value) : sessionStorage.removeItem(KEY);
export function errorText(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(errorText).join("; ");
  return Object.entries(value || {})
    .map(([key, val]) => `${key}: ${errorText(val)}`)
    .join("; ");
}
export async function api(path, options = {}, token = getToken()) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Token ${token}` } : {}),
      ...options.headers,
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      errorText(data.error || data.detail || data.non_field_errors || data) ||
        "Ошибка запроса",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
export function printResult(id, revisionId) {
  return openPrintDocument(
    `/api/results/${id}/print/${revisionId ? `?revision=${revisionId}` : ""}`,
    getToken(),
  );
}
