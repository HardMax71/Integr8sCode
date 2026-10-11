import { QueryClient } from '@tanstack/svelte-query';

export const queryClient = new QueryClient({
    defaultOptions: {
        // The fetch interceptor in api-interceptors.ts toasts every failed request, so each retry would toast again
        queries: { retry: false },
    },
});
