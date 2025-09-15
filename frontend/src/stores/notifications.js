import { writable } from "svelte/store";

export const notifications = writable([]);

// Standard notification display duration in milliseconds
export const NOTIFICATION_DURATION = 5000;

export function addNotification(message, type = "info") {
  const id = Math.random().toString(36).substr(2, 9);
  const text = `${message?.message ?? message?.detail ?? message}`;
  notifications.update(n => [...n, { id, message: text, type }]);
  setTimeout(() => removeNotification(id), NOTIFICATION_DURATION);
}

export function removeNotification(id) {
  notifications.update(n => n.filter(notification => notification.id !== id));
}
