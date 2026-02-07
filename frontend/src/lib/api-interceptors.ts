import { client } from '$lib/api/client.gen';
import { toast } from 'svelte-sonner';
import { goto } from '@mateothegreat/svelte5-router';
import { authStore } from '$stores/auth.svelte';

let isHandling401 = false;
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/verify-token'];

const STATUS_MESSAGES: Record<number, { message: string; type: 'error' | 'warning' }> = {
    403: { message: 'Access denied.', type: 'error' },
    429: { message: 'Too many requests. Please slow down.', type: 'warning' },
};

export function getErrorMessage(err: unknown, fallback = 'An error occurred'): string {
    if (!err) return fallback;
    if (typeof err === 'string') return err;
    if (err instanceof Error) return err.message;
    if (typeof err !== 'object') return fallback;

    const obj = err as Record<string, unknown>;

    if (typeof obj.detail === 'string') return obj.detail;
    if (typeof obj.message === 'string') return obj.message;

    // FastAPI ValidationError[] or [{msg: '...'}]
    if (Array.isArray(obj.detail)) {
        return (obj.detail as Array<{ loc?: unknown[]; msg?: string }>)
            .map(e => {
                const msg = e.msg ?? 'Unknown error';
                if (!e.loc?.length) return msg;
                const field = e.loc[e.loc.length - 1];
                return `${typeof field === 'string' ? field : 'field'}: ${msg}`;
            })
            .join(', ');
    }

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

    if (status === 422 && typeof error === 'object' && error !== null) {
        const detail = (error as Record<string, unknown>).detail;
        if (Array.isArray(detail) && detail.length > 0) {
            toast.error(`Validation error:\n${getErrorMessage(error)}`);
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

    client.interceptors.error.use((error, response, request, _opts) => {
        const status = response.status;
        const url = request.url;
        const isAuthEndpoint = AUTH_ENDPOINTS.some(ep => url.includes(ep));

        console.error('[API Error]', { status, url, error });

        const handled = handleErrorStatus(status, error, isAuthEndpoint);
        if (!handled && !isAuthEndpoint) {
            toast.error(getErrorMessage(error, 'An error occurred'));
        }

        return error;
    });

    client.interceptors.request.use((request, _opts) => {
        if (request.method !== 'GET') {
            const token = authStore.csrfToken;
            if (token) {
                request.headers.set('X-CSRF-Token', token);
            }
        }
        return request;
    });
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
