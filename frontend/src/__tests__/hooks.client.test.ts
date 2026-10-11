import { describe, it, expect, vi } from 'vitest';
import { initializeApiInterceptors } from '#lib/api-interceptors.ts';
import { handleError, init } from '../hooks.client.ts';

describe('client hooks', () => {
    it('sets up the API interceptors once the app starts', async () => {
        await init();
        expect(vi.mocked(initializeApiInterceptors)).toHaveBeenCalledOnce();
    });

    it('logs an unexpected error and keeps the default error object', async () => {
        const result = await handleError({
            kind: 'unknown',
            error: new Error('boom'),
            event: { url: new URL('https://localhost/editor') },
        } as Parameters<typeof handleError>[0]);
        expect(result).toBeUndefined();
    });
});
