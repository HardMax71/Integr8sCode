import { vi } from 'vitest';

export const getErrorMessage = (err: unknown, fallback = 'An error occurred'): string => {
    if (!err) return fallback;
    if (typeof err === 'object' && 'message' in err) return String((err as { message: unknown }).message);
    if (typeof err === 'string') return err;
    return fallback;
};

export const initializeApiInterceptors = vi.fn();

export function unwrap<T>(result: { data?: T; error?: unknown }): T | undefined {
    if (result.error) return undefined;
    return result.data as T;
}

export function unwrapOr<T>(result: { data?: T; error?: unknown }, fallback: T): T {
    return result.error ? fallback : (result.data as T);
}
