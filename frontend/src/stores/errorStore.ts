import { writable } from 'svelte/store';

export interface AppError {
  error: Error | string;
  title?: string;
  timestamp: number;
}

function createErrorStore() {
  const { subscribe, set, update } = writable<AppError | null>(null);

  return {
    subscribe,
    setError: (error: Error | string, title?: string) => {
      console.error('[ErrorStore]', title || 'Error:', error);
      set({
        error,
        title,
        timestamp: Date.now()
      });
    },
    clear: () => set(null)
  };
}

export const appError = createErrorStore();
