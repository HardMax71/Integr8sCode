import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { QueryObserver } from '@tanstack/svelte-query';
import { ApiError } from '#lib/api-error.ts';
import { queryClient, setQueryErrorHandler } from '#lib/query-client.ts';

describe('queryClient', () => {
    const handler = vi.fn();

    beforeEach(() => {
        handler.mockReset();
        setQueryErrorHandler(handler);
    });

    afterEach(() => {
        setQueryErrorHandler(() => {});
    });

    // An observer, like createQuery, so the client's default retry applies
    async function failingQuery(error: unknown): Promise<number> {
        const queryFn = vi.fn().mockRejectedValue(error);
        const unsubscribe = new QueryObserver(queryClient, { queryKey: ['failing', String(error)], queryFn }).subscribe(
            () => {},
        );
        await vi.advanceTimersByTimeAsync(5000);
        unsubscribe();
        return queryFn.mock.calls.length;
    }

    it.each([
        ['a network error', new ApiError(undefined, new TypeError('Failed to fetch'))],
        ['a 503', new ApiError(503, { detail: 'Service Unavailable' })],
    ])('retries %s twice, then reports it once', async (_label, error) => {
        expect(await failingQuery(error)).toBe(3);
        expect(handler).toHaveBeenCalledTimes(1);
        expect(handler).toHaveBeenCalledWith(error, false);
    });

    it.each([
        ['a 404', new ApiError(404, { detail: 'Not found' })],
        ['a 401', new ApiError(401, { detail: 'Not authenticated' })],
        ['an error that never reached the server', new TypeError('Invalid URL')],
    ])('reports %s without retrying', async (_label, error) => {
        expect(await failingQuery(error)).toBe(1);
        expect(handler).toHaveBeenCalledWith(error, false);
    });

    it.each([
        [{ inlineErrors: true }, true],
        [undefined, false],
    ])('passes the mutation meta %o on as inlineErrors=%s, without retrying', async (meta, inline) => {
        const error = new ApiError(500, { detail: 'boom' });
        const mutationFn = vi.fn().mockRejectedValue(error);
        const mutation = queryClient.getMutationCache().build(queryClient, { mutationFn, meta });

        await expect(mutation.execute(undefined)).rejects.toBe(error);

        expect(mutationFn).toHaveBeenCalledTimes(1);
        expect(handler).toHaveBeenCalledWith(error, inline);
    });

    it('keeps the previous data when a refetch returns the same values in new Date objects', async () => {
        const queryKey = ['shared'];
        const first = { name: 'a', at: new Date('2026-01-01T00:00:00Z') };
        const queryFn = vi
            .fn()
            .mockResolvedValueOnce(first)
            .mockResolvedValueOnce({ name: 'a', at: new Date('2026-01-01T00:00:00Z') })
            .mockResolvedValueOnce({ name: 'a', at: new Date('2026-01-02T00:00:00Z') });
        const observer = new QueryObserver(queryClient, { queryKey, queryFn });
        const unsubscribe = observer.subscribe(() => {});
        await vi.waitFor(() => expect(observer.getCurrentResult().data).toBe(first));

        await observer.refetch();
        expect(observer.getCurrentResult().data).toBe(first);

        await observer.refetch();
        expect(observer.getCurrentResult().data).toEqual({ name: 'a', at: new Date('2026-01-02T00:00:00Z') });
        unsubscribe();
    });
});
