import { writable } from "svelte/store";

export const notifications = writable([]);

export function addNotification(message, type = "info") {
  const id = Math.random().toString(36).substr(2, 9);
  notifications.update(n => [...n, { id, message, type }]);
  setTimeout(() => removeNotification(id), 5000);
}

export function removeNotification(id) {
  notifications.update(n => n.filter(notification => notification.id !== id));
}