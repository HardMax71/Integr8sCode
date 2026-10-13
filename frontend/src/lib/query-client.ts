import { MutationCache, QueryCache, QueryClient } from '@tanstack/svelte-query';
import type { ErrorResponse } from '#lib/api/index.ts';

declare module '@tanstack/svelte-query' {
    interface Register {
        /** The client's error interceptor turns every failure into one, network errors included (status 0) */
        defaultError: ErrorResponse;
        mutationMeta: {
            /** The form shows 401s, network errors and other 4xx itself; app-wide messages still toast */
            inlineErrors?: boolean;
        };
    }
}

type ErrorHandler = (error: ErrorResponse, inlineErrors: boolean) => void;

let handleError: ErrorHandler = () => {};

/** api-interceptors.ts sets the handler at startup, since it imports the auth store, which imports this module. */
export function setQueryErrorHandler(handler: ErrorHandler): void {
    handleError = handler;
}

const MAX_RETRIES = 2;

export const queryClient = new QueryClient({
    queryCache: new QueryCache({
        onError: (error) => {
            handleError(error, false);
        },
    }),
    mutationCache: new MutationCache({
        onError: (error, _variables, _result, mutation) => {
            handleError(error, mutation.meta?.inlineErrors === true);
        },
    }),
    defaultOptions: {
        queries: {
            // A network error or a 5xx may pass on another try, a 4xx won't; the default backoff waits 1s, then 2s
            retry: (failures, error) => failures < MAX_RETRIES && (error.status === 0 || error.status >= 500),
        },
    },
});
