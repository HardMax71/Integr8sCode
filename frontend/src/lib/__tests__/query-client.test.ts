import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { QueryObserver } from '@tanstack/svelte-query';
import type { ErrorResponse } from '#lib/api/index.ts';
import { queryClient, setQueryErrorHandler } from '#lib/query-client.ts';

describe('queryClient', () => {
    const handler = vi.fn();

    beforeEach(() => {
        setQueryErrorHandler(handler);
    });

    afterEach(() => {
        setQueryErrorHandler(() => {});
    });

    // An observer, like createQuery, so the client's default retry applies
    async function failingQuery(error: ErrorResponse): Promise<number> {
        const queryFn = vi.fn().mockRejectedValue(error);
        const unsubscribe = new QueryObserver(queryClient, { queryKey: ['failing', error.status], queryFn }).subscribe(
            () => {},
        );
        await vi.advanceTimersByTimeAsync(5000);
        unsubscribe();
        return queryFn.mock.calls.length;
    }

    it.each([
        ['a network error', { status: 0, detail: 'Network error. Check your connection.' }],
        ['a 503', { status: 503, detail: 'Service Unavailable' }],
    ])('retries %s twice, then reports it once', async (_label, error) => {
        expect(await failingQuery(error)).toBe(3);
        expect(handler).toHaveBeenCalledTimes(1);
        expect(handler).toHaveBeenCalledWith(error, false);
    });

    it.each([
        ['a 404', { status: 404, detail: 'Not found' }],
        ['a 401', { status: 401, detail: 'Not authenticated' }],
    ])('reports %s without retrying', async (_label, error) => {
        expect(await failingQuery(error)).toBe(1);
        expect(handler).toHaveBeenCalledWith(error, false);
    });

    it.each([
        [{ inlineErrors: true }, true],
        [undefined, false],
    ])('passes the mutation meta %o on as inlineErrors=%s, without retrying', async (meta, inline) => {
        const error = { status: 500, detail: 'boom' };
        const mutationFn = vi.fn().mockRejectedValue(error);
        const mutation = queryClient.getMutationCache().build(queryClient, { mutationFn, meta });

        await expect(mutation.execute(undefined)).rejects.toBe(error);

        expect(mutationFn).toHaveBeenCalledTimes(1);
        expect(handler).toHaveBeenCalledWith(error, inline);
    });
});
