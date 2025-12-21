import { writable } from 'svelte/store';

export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
    id: string;
    message: string;
    type: ToastType;
    progress?: number;
    timerStarted?: boolean;
}

export const toasts = writable<Toast[]>([]);
export const TOAST_DURATION = 5000;

export function addToast(message: unknown, type: ToastType = 'info'): void {
    const id = Math.random().toString(36).substring(2, 11);
    const text = typeof message === 'object' && message !== null
        ? (message as { message?: string; detail?: string }).message
          ?? (message as { message?: string; detail?: string }).detail
          ?? String(message)
        : String(message);
    toasts.update(n => [...n, { id, message: text, type }]);
    setTimeout(() => removeToast(id), TOAST_DURATION);
}

export function removeToast(id: string): void {
    toasts.update(n => n.filter(toast => toast.id !== id));
}
