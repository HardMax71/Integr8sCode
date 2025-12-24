import { client } from './api/client.gen';
import { addToast } from '../stores/toastStore';
import { goto } from '@mateothegreat/svelte5-router';
import {
    isAuthenticated,
    username,
    userId,
    userRole,
    userEmail,
    csrfToken,
} from '../stores/auth';
import { get } from 'svelte/store';
import type { ValidationError } from './api';

let isHandling401 = false;
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/verify-token'];

export function getErrorMessage(err: unknown, fallback = 'An error occurred'): string {
    if (!err) return fallback;

    if (typeof err === 'object' && 'detail' in err) {
        const detail = (err as { detail?: ValidationError[] | string }).detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail) && detail.length > 0) {
            return detail.map((e) => `${e.loc[e.loc.length - 1]}: ${e.msg}`).join(', ');
        }
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
    localStorage.removeItem('authState');
}

function handleAuthFailure(currentPath: string): void {
    clearAuthState();
    if (currentPath !== '/login' && currentPath !== '/register') {
        sessionStorage.setItem('redirectAfterLogin', currentPath);
    }
    goto('/login');
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

        if (status === 401 && !isAuthEndpoint && !isHandling401) {
            isHandling401 = true;
            try {
                const currentPath = window.location.pathname + window.location.search;
                addToast('Session expired. Please log in again.', 'warning');
                handleAuthFailure(currentPath);
            } finally {
                setTimeout(() => { isHandling401 = false; }, 1000);
            }
            return { _handled: true, _status: 401 };
        }

        if (status === 403) {
            addToast('Access denied.', 'error');
            return error;
        }

        if (status === 422 && typeof error === 'object' && error !== null && 'detail' in error) {
            const detail = (error as { detail: ValidationError[] }).detail;
            if (Array.isArray(detail) && detail.length > 0) {
                addToast(`Validation error:\n${formatValidationErrors(detail)}`, 'error');
                return error;
            }
        }

        if (status === 429) {
            addToast('Too many requests. Please slow down.', 'warning');
            return error;
        }

        if (status && status >= 500) {
            addToast('Server error. Please try again later.', 'error');
            return error;
        }

        if (!response && !url.includes('/verify-token')) {
            addToast('Network error. Check your connection.', 'error');
            return error;
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
