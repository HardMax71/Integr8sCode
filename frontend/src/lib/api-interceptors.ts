import { client, zErrorResponse, type ErrorResponse } from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';
import { refreshAll } from '$app/navigation';
import { page } from '$app/state';
import { queryClient, setQueryErrorHandler } from '#lib/query-client.ts';
import { getLogger } from '@logtape/logtape';

const log = getLogger(['integr8scode', 'api']);

const STATUS_MESSAGES: Record<number, { message: string; type: 'error' | 'warning' }> = {
    403: { message: 'Access denied.', type: 'error' },
    423: {
        message:
            'Your account has been temporarily locked due to too many failed login attempts. Please try again later.',
        type: 'warning',
    },
    429: { message: 'Too many requests. Please slow down.', type: 'warning' },
};

// --8<-- [start:error_handling]
/** A signed-in user's 401 means the session expired; the reloaded layout data then sends a guarded page to /login */
function handle401(): void {
    if (!page.data.user) return;
    // The id keeps the 401s of one page's parallel requests to one toast
    toast.warning('Session expired. Please log in again.', { id: 'session-expired' });
    // Nothing the previous user loaded may show to the next one
    queryClient.clear();
    void refreshAll();
}

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
        const problem = zErrorResponse.safeParse(error);
        let failure: ErrorResponse = { status: 0, detail: 'Network error. Check your connection.' };
        if (problem.success) failure = problem.data;
        else if (response) failure = { status: response.status, detail: `HTTP ${response.status}` };
        // A 4xx is the API answering as designed, and the user sees it in a toast or the form
        const line = { method: request?.method ?? opts.method, url: request?.url ?? opts.url, ...failure };
        if (failure.status === 0 || failure.status >= 500)
            log.error('{method} {url} failed with {status}: {detail}', line);
        else log.debug('{method} {url} failed with {status}: {detail}', line);
        return failure;
    });

    // --8<-- [start:csrf_injection]
    // The double-submit pattern: the header echoes the readable csrf_token cookie that login set
    client.interceptors.request.use((request) => {
        const csrfToken = /(?:^|;\s*)csrf_token=([^;]*)/.exec(document.cookie)?.[1];
        if (request.method !== 'GET' && csrfToken) request.headers.set('X-CSRF-Token', csrfToken);
        return request;
    });
    // --8<-- [end:csrf_injection]
}
