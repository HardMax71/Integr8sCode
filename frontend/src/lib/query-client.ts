import { MutationCache, QueryCache, QueryClient } from '@tanstack/svelte-query';
import { ApiError } from '#lib/api-error.ts';

declare module '@tanstack/svelte-query' {
    interface Register {
        mutationMeta: {
            /** The form shows 401s, network errors and other 4xx itself; app-wide messages still toast */
            inlineErrors?: boolean;
        };
    }
}

type ErrorHandler = (error: unknown, inlineErrors: boolean) => void;

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
            // --8<-- [start:sharing]
            // The default sharing treats every Date as changed; comparing the JSON keeps unchanged data, dates included
            structuralSharing: (previous, next) =>
                JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
            // --8<-- [end:sharing]
            // A network error or a 5xx may pass on another try, a 4xx won't; the default backoff waits 1s, then 2s
            retry: (failures, error) =>
                failures < MAX_RETRIES &&
                error instanceof ApiError &&
                (error.status === undefined || error.status >= 500),
        },
    },
});
