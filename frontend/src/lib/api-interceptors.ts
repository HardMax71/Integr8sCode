import { client, type ValidationError } from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';
import { goto } from '$app/navigation';
import { authStore } from '#stores/auth.svelte.ts';
import { ApiError } from '#lib/api-error.ts';
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

function isValidationErrorArray(value: unknown): value is ValidationError[] {
    if (!Array.isArray(value) || value.length === 0) return false;
    const first = value[0] as Record<string, unknown>;
    return typeof first.msg === 'string' && Array.isArray(first.loc);
}

function formatValidationErrors(errors: ValidationError[]): string {
    return errors
        .map((e) => {
            if (!e.loc.length) return e.msg;
            const field = e.loc.at(-1);
            return `${typeof field === 'string' ? field : 'field'}: ${e.msg}`;
        })
        .join(', ');
}

export function getErrorMessage(err: unknown, fallback = 'An error occurred'): string {
    if (!err) return fallback;
    if (err instanceof ApiError) return getErrorMessage(err.body, fallback);
    if (typeof err === 'string') return err;

    if (typeof err === 'object' && 'detail' in err) {
        const { detail } = err;
        if (typeof detail === 'string') return detail;
        if (isValidationErrorArray(detail)) return formatValidationErrors(detail);
    }

    if (err instanceof Error) return err.message;

    return fallback;
}

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
        void goto('/login');
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
 * @param error - What the request threw; anything but an ApiError failed before it was sent and is only logged
 * @param inlineErrors - The form shows 401s, network errors and other 4xx itself
 */
export function showApiError(error: unknown, inlineErrors: boolean): void {
    if (!(error instanceof ApiError)) return;
    const { status } = error;

    if (status === undefined) {
        if (!inlineErrors) toast.error('Network error. Check your connection.');
        return;
    }
    if (status === 401) {
        if (!inlineErrors) handle401();
        return;
    }

    const mapped = STATUS_MESSAGES[status];
    if (mapped) {
        toast[mapped.type](mapped.message);
    } else if (status === 422) {
        toast.error(`Validation error: ${getErrorMessage(error)}`);
    } else if (status >= 500) {
        toast.error('Server error. Please try again later.');
    } else if (!inlineErrors) {
        toast.error(getErrorMessage(error));
    }
}
// --8<-- [end:error_handling]

export function initializeApiInterceptors(): void {
    client.setConfig({
        baseUrl: '',
        credentials: 'include',
    });

    setQueryErrorHandler(showApiError);

    client.interceptors.error.use((error, response: Response | undefined, request, opts) => {
        log.error('API Error', { status: response?.status, url: request?.url ?? opts.url, error });
        // No request means it failed before it was sent, so there's no status to report
        return request ? new ApiError(response?.status, error) : error;
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
