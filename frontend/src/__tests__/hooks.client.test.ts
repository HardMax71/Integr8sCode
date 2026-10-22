import { afterEach, describe, it, expect, vi } from 'vitest';
import { getConfig, reset } from '@logtape/logtape';
import { initializeApiInterceptors } from '#lib/api-interceptors.ts';
import { captureLogs } from '#test/test-utils.ts';
import { handleError, init } from '../hooks.client.ts';

describe('client hooks', () => {
    afterEach(async () => {
        await reset();
    });

    it('sends every record to the collector, sets up the API interceptors and logs uncaught errors', async () => {
        await init();
        expect(getConfig()?.loggers).toEqual([
            { category: 'integr8scode', sinks: ['otel'] },
            { category: ['logtape', 'meta'], lowestLevel: 'warning', sinks: ['otel'] },
        ]);
        expect(vi.mocked(initializeApiInterceptors)).toHaveBeenCalledOnce();

        await reset();
        const records = captureLogs();
        const error = new Error('boom');
        window.dispatchEvent(new ErrorEvent('error', { error }));
        window.dispatchEvent(
            new ErrorEvent('error', { message: 'ResizeObserver loop completed with undelivered notifications.' }),
        );
        window.dispatchEvent(Object.assign(new Event('unhandledrejection'), { reason: 'offline' }));
        expect(records).toEqual([
            expect.objectContaining({ level: 'error', message: ['Uncaught error: ', error, ''] }),
            expect.objectContaining({ level: 'error', message: ['Unhandled rejection: ', 'offline', ''] }),
        ]);
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
