import { writable } from "svelte/store";

export const toasts = writable([]);

export const TOAST_DURATION = 5000;

export function addToast(message, type = "info") {
  const id = Math.random().toString(36).substr(2, 9);
  const text = `${message?.message ?? message?.detail ?? message}`;
  toasts.update(n => [...n, { id, message: text, type }]);
  setTimeout(() => removeToast(id), TOAST_DURATION);
}

export function removeToast(id) {
  toasts.update(n => n.filter(toast => toast.id !== id));
}
