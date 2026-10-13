import { client, zErrorResponse, type ErrorResponse } from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { authStore } from '#stores/auth.svelte.ts';
import { setQueryErrorHandler } from '#lib/query-client.ts';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('API');

let isHandling401 = false;

const STATUS_MESSAGES: Record<number, { message: string; type: 'error' | 'warning' }> = {
    403: { message: 'Access denied.', type: 'error' },
    423: {
        message:
            'Your account has been temporarily locked due to too many failed login attempts. Please try again later.',
        type: 'warning',
    },
    429: { message: 'Too many requests. Please slow down.', type: 'warning' },
};

function handle401(): void {
    const wasAuthenticated = authStore.isAuthenticated;
    if (wasAuthenticated && !isHandling401) {
        isHandling401 = true;
        const currentPath = window.location.pathname + window.location.search;
        toast.warning('Session expired. Please log in again.');
        authStore.clearAuth();
        if (currentPath !== '/login' && currentPath !== '/register') {
            sessionStorage.setItem('redirectAfterLogin', currentPath);
        }
        void goto(resolve('/login'));
        setTimeout(() => {
            isHandling401 = false;
        }, 1000);
    } else {
        authStore.clearAuth();
    }
}

// --8<-- [start:error_handling]
/**
 * Shows a failed query or mutation; the query client calls it once a query has used up its retries.
 * @param inlineErrors - The form shows 401s, network errors and other 4xx itself
 */
export function showApiError({ status, detail }: ErrorResponse, inlineErrors: boolean): void {
    if (status === 401) {
        if (!inlineErrors) handle401();
        return;
    }
    const mapped = STATUS_MESSAGES[status];
    if (mapped) {
        toast[mapped.type](mapped.message);
    } else if (status === 422) {
        toast.error(`Validation error: ${detail}`);
    } else if (status >= 500) {
        toast.error('Server error. Please try again later.');
    } else if (!inlineErrors) {
        toast.error(detail);
    }
}
// --8<-- [end:error_handling]

export function initializeApiInterceptors(): void {
    client.setConfig({
        baseUrl: '',
        credentials: 'include',
    });

    setQueryErrorHandler(showApiError);

    // A body that isn't an ErrorResponse, like a proxy's error page, or no response at all becomes one
    client.interceptors.error.use((error, response, request, opts) => {
        log.error('API Error', { status: response?.status, url: request?.url ?? opts.url, error });
        const problem = zErrorResponse.safeParse(error);
        if (problem.success) return problem.data;
        return response
            ? { status: response.status, detail: `HTTP ${response.status}` }
            : { status: 0, detail: 'Network error. Check your connection.' };
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
