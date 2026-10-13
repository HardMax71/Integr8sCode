import { afterEach, describe, it, expect, vi } from 'vitest';
import { getConfig, resetSync } from '@logtape/logtape';
import { initializeApiInterceptors } from '#lib/api-interceptors.ts';
import { captureLogs } from '#test/test-utils.ts';
import { handleError, init } from '../hooks.client.ts';

describe('client hooks', () => {
    afterEach(() => {
        resetSync();
    });

    it('configures logging and sets up the API interceptors once the app starts', async () => {
        await init();
        expect(getConfig()?.loggers.map((logger) => logger.category)).toEqual(['integr8scode', ['logtape', 'meta']]);
        expect(vi.mocked(initializeApiInterceptors)).toHaveBeenCalledOnce();
    });

    it('logs an unexpected error with its kind, path and the error, and keeps the default error object', async () => {
        const records = captureLogs();
        const error = new Error('boom');

        const result = await handleError({
            kind: 'unknown',
            error,
            event: { url: new URL('https://localhost/editor') },
        } as Parameters<typeof handleError>[0]);

        expect(result).toBeUndefined();
        expect(records).toEqual([
            expect.objectContaining({
                level: 'error',
                category: ['integr8scode', 'app'],
                message: ['Unexpected ', 'unknown', ' error on ', '/editor', ': ', error, ''],
            }),
        ]);
    });
});
