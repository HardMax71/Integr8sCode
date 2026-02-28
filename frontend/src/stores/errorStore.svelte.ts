import { logger } from '$lib/logger';

const log = logger.withTag('ErrorStore');

export interface AppError {
    error: Error | string;
    title?: string;
    timestamp: number;
}

class ErrorStore {
    current = $state<AppError | null>(null);

    setError(error: Error | string, title?: string): void {
        log.error(title || 'Error:', error);
        this.current = { error, title, timestamp: Date.now() };
    }

    clear(): void {
        this.current = null;
    }
}

export const appError = new ErrorStore();
