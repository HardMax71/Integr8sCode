import { client } from '$lib/api/client.gen';
import { toast } from 'svelte-sonner';
import { goto } from '@mateothegreat/svelte5-router';
import {
    isAuthenticated,
    username,
    userId,
    userRole,
    userEmail,
    csrfToken,
} from '$stores/auth';
import { get } from 'svelte/store';
import type { ValidationError } from '$lib/api';

let isHandling401 = false;
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/verify-token'];

const STATUS_MESSAGES: Record<number, { message: string; type: 'error' | 'warning' }> = {
    403: { message: 'Access denied.', type: 'error' },
    429: { message: 'Too many requests. Please slow down.', type: 'warning' },
};

function extractDetail(err: unknown): string | ValidationError[] | null {
    if (typeof err === 'object' && err !== null && 'detail' in err) {
        return (err as { detail: string | ValidationError[] }).detail;
    }
    return null;
}

export function getErrorMessage(err: unknown, fallback = 'An error occurred'): string {
    if (!err) return fallback;

    const detail = extractDetail(err);
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
        return detail.map((e) => `${e.loc[e.loc.length - 1]}: ${e.msg}`).join(', ');
    }

    if (err instanceof Error) return err.message;
    if (typeof err === 'string') return err;
    if (typeof err === 'object' && 'message' in err) {
        return String((err as { message: unknown }).message);
    }

    return fallback;
}

function formatValidationErrors(detail: ValidationError[]): string {
    return detail.map((e) => `${e.loc[e.loc.length - 1]}: ${e.msg}`).join('\n');
}

function clearAuthState(): void {
    isAuthenticated.set(false);
    username.set(null);
    userId.set(null);
    userRole.set(null);
    userEmail.set(null);
    csrfToken.set(null);
    sessionStorage.removeItem('authState');
}

function handle401(isAuthEndpoint: boolean): void {
    if (isAuthEndpoint) return;

    const wasAuthenticated = get(isAuthenticated);
    if (wasAuthenticated && !isHandling401) {
        isHandling401 = true;
        const currentPath = window.location.pathname + window.location.search;
        toast.warning('Session expired. Please log in again.');
        clearAuthState();
        if (currentPath !== '/login' && currentPath !== '/register') {
            sessionStorage.setItem('redirectAfterLogin', currentPath);
        }
        goto('/login');
        setTimeout(() => { isHandling401 = false; }, 1000);
    } else {
        clearAuthState();
    }
}

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
        const detail = extractDetail(error);
        if (Array.isArray(detail) && detail.length > 0) {
            toast.error(`Validation error:\n${formatValidationErrors(detail)}`);
            return true;
        }
    }

    if (status >= 500) {
        toast.error('Server error. Please try again later.');
        return true;
    }

    return false;
}

export function initializeApiInterceptors(): void {
    client.setConfig({
        baseUrl: '',
        credentials: 'include',
    });

    client.interceptors.error.use(async (error, response, request, _opts) => {
        const status = response?.status;
        const url = request?.url || '';
        const isAuthEndpoint = AUTH_ENDPOINTS.some(ep => url.includes(ep));

        console.error('[API Error]', { status, url, error });

        const handled = handleErrorStatus(status, error, isAuthEndpoint);
        if (!handled && !isAuthEndpoint) {
            toast.error(getErrorMessage(error, 'An error occurred'));
        }

        return error;
    });

    client.interceptors.request.use(async (request, _opts) => {
        if (request.method !== 'GET') {
            const token = get(csrfToken);
            if (token) {
                request.headers.set('X-CSRF-Token', token);
            }
        }
        return request;
    });
}

export function unwrap<T>(result: { data?: T; error?: unknown }): T {
    if (result.error) throw result.error;
    return result.data as T;
}

export function unwrapOr<T>(result: { data?: T; error?: unknown }, fallback: T): T {
    return result.error ? fallback : (result.data as T);
}
