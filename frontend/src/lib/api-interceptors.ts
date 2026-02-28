import { client } from '$lib/api/client.gen';
import type { ValidationError } from '$lib/api';
import { toast } from 'svelte-sonner';
import { goto } from '@mateothegreat/svelte5-router';
import { authStore } from '$stores/auth.svelte';
import { logger } from '$lib/logger';

const log = logger.withTag('API');

let isHandling401 = false;
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/register'];

const STATUS_MESSAGES: Record<number, { message: string; type: 'error' | 'warning' }> = {
    403: { message: 'Access denied.', type: 'error' },
    423: { message: 'Your account has been temporarily locked due to too many failed login attempts. Please try again later.', type: 'warning' },
    429: { message: 'Too many requests. Please slow down.', type: 'warning' },
};

function isValidationErrorArray(value: unknown): value is ValidationError[] {
    if (!Array.isArray(value) || value.length === 0) return false;
    const first = value[0] as Record<string, unknown>;
    return typeof first.msg === 'string' && Array.isArray(first.loc);
}

function formatValidationErrors(errors: ValidationError[]): string {
    return errors.map(e => {
        if (!e.loc.length) return e.msg;
        const field = e.loc[e.loc.length - 1];
        return `${typeof field === 'string' ? field : 'field'}: ${e.msg}`;
    }).join(', ');
}

export function getErrorMessage(err: unknown, fallback = 'An error occurred'): string {
    if (!err) return fallback;
    if (typeof err === 'string') return err;

    if (typeof err === 'object' && 'detail' in err) {
        const { detail } = err as { detail: unknown };
        if (typeof detail === 'string') return detail;
        if (isValidationErrorArray(detail)) return formatValidationErrors(detail);
    }

    if (err instanceof Error) return err.message;

    return fallback;
}


function handle401(isAuthEndpoint: boolean): void {
    if (isAuthEndpoint) return;

    const wasAuthenticated = authStore.isAuthenticated;
    if (wasAuthenticated && !isHandling401) {
        isHandling401 = true;
        const currentPath = window.location.pathname + window.location.search;
        toast.warning('Session expired. Please log in again.');
        authStore.clearAuth();
        if (currentPath !== '/login' && currentPath !== '/register') {
            sessionStorage.setItem('redirectAfterLogin', currentPath);
        }
        goto('/login');
        setTimeout(() => { isHandling401 = false; }, 1000);
    } else {
        authStore.clearAuth();
    }
}

// --8<-- [start:error_handling]
function handleErrorStatus(status: number | undefined, error: unknown, isAuthEndpoint: boolean): boolean {
    if (!status) {
        if (!isAuthEndpoint) toast.error('Network error. Check your connection.');
        return true;
    }

    if (status === 401) {
        handle401(isAuthEndpoint);
        return true;
    }

    const mapped = STATUS_MESSAGES[status];
    if (mapped) {
        toast[mapped.type](mapped.message);
        return true;
    }

    if (status === 422) {
        toast.error(`Validation error: ${getErrorMessage(error)}`);
        return true;
    }

    if (status >= 500) {
        toast.error('Server error. Please try again later.');
        return true;
    }

    return false;
}
// --8<-- [end:error_handling]

export function initializeApiInterceptors(): void {
    client.setConfig({
        baseUrl: '',
        credentials: 'include',
    });

    client.interceptors.error.use((error, response: Response | undefined, request, _opts) => {
        const status = response?.status;
        const url = request.url;
        const isAuthEndpoint = AUTH_ENDPOINTS.some(ep => url.includes(ep));

        log.error('API Error', { status, url, error });

        const handled = handleErrorStatus(status, error, isAuthEndpoint);
        if (!handled && !isAuthEndpoint) {
            toast.error(getErrorMessage(error, 'An error occurred'));
        }

        return error;
    });

    // --8<-- [start:csrf_injection]
    client.interceptors.request.use((request, _opts) => {
        if (request.method !== 'GET') {
            const token = authStore.csrfToken;
            if (token) {
                request.headers.set('X-CSRF-Token', token);
            }
        }
        return request;
    });
    // --8<-- [end:csrf_injection]
}

export function unwrap<T>(result: { data?: T; error?: unknown }): T {
    if (result.error) throw result.error;
    if (result.data === undefined) {
        throw new Error('Unexpected empty response');
    }
    return result.data;
}

export function unwrapOr<T>(result: { data?: T; error?: unknown }, fallback: T): T {
    if (result.error || result.data === undefined) {
        return fallback;
    }
    return result.data;
}
