import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { effect_root } from 'svelte/internal/client';
import { createMockExecution, createMockQueueStatus } from '$test/test-utils';

const mocks = vi.hoisted(() => ({
    listExecutionsApiV1AdminExecutionsGet: vi.fn(),
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut: vi.fn(),
    getQueueStatusApiV1AdminExecutionsQueueGet: vi.fn(),
    unwrap: vi.fn((result: { data: unknown }) => result?.data),
    unwrapOr: vi.fn((result: { data: unknown }, fallback: unknown) => result?.data ?? fallback),
    toastSuccess: vi.fn(),
}));

vi.mock('$lib/api', () => ({
    listExecutionsApiV1AdminExecutionsGet: (...args: unknown[]) => mocks.listExecutionsApiV1AdminExecutionsGet(...args),
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut: (...args: unknown[]) => mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut(...args),
    getQueueStatusApiV1AdminExecutionsQueueGet: (...args: unknown[]) => mocks.getQueueStatusApiV1AdminExecutionsQueueGet(...args),
}));

vi.mock('$lib/api-interceptors', () => ({
    unwrap: (result: { data: unknown }) => mocks.unwrap(result),
    unwrapOr: (result: { data: unknown }, fallback: unknown) => mocks.unwrapOr(result, fallback),
}));

vi.mock('svelte-sonner', () => ({
    toast: {
        success: (...args: unknown[]) => mocks.toastSuccess(...args),
        error: vi.fn(),
        info: vi.fn(),
        warning: vi.fn(),
    },
}));

const { createExecutionsStore } = await import('../executionsStore.svelte');

function setupDefaultMocks() {
    mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
        data: { executions: [], total: 0, limit: 20, skip: 0, has_more: false },
    });
    mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
        data: createMockQueueStatus(),
    });
    mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut.mockResolvedValue({
        data: null,
    });
}

describe('ExecutionsStore', () => {
    let store: ReturnType<typeof createExecutionsStore>;
    let teardown: () => void;

    beforeEach(() => {
        vi.clearAllMocks();
        setupDefaultMocks();
    });

    /**
     * Creates a store with auto-refresh timers immediately cleared.
     * The $effect fires synchronously inside effect_root, starting a
     * setInterval. We clear all timers, reset mocks, and re-apply defaults
     * so individual tests control timing explicitly.
     */
    function createStore() {
        teardown = effect_root(() => {
            store = createExecutionsStore();
        });
        vi.clearAllTimers();
        vi.clearAllMocks();
        setupDefaultMocks();
    }

    function createStoreWithAutoRefresh() {
        teardown = effect_root(() => {
            store = createExecutionsStore();
        });
    }

    afterEach(() => {
        teardown?.();
        vi.clearAllTimers();
    });

    describe('initial state', () => {
        it('starts with empty data', () => {
            createStore();
            expect(store.executions).toEqual([]);
            expect(store.total).toBe(0);
            expect(store.loading).toBe(false);
            expect(store.queueStatus).toBeNull();
        });

        it('starts with default filters', () => {
            createStore();
            expect(store.statusFilter).toBe('all');
            expect(store.priorityFilter).toBe('all');
            expect(store.userSearch).toBe('');
        });
    });

    describe('loadData', () => {
        it('loads executions and queue status', async () => {
            createStore();
            const execs = [createMockExecution()];
            mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
                data: { executions: execs, total: 1 },
            });
            mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
                data: createMockQueueStatus(),
            });

            await store.loadData();

            expect(store.executions).toEqual(execs);
            expect(store.total).toBe(1);
            expect(store.queueStatus).toEqual(createMockQueueStatus());
        });

        it('handles empty API response', async () => {
            createStore();
            mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({ data: null });

            await store.loadExecutions();

            expect(store.executions).toEqual([]);
            expect(store.total).toBe(0);
        });
    });

    describe('loadExecutions with filters', () => {
        it('passes status filter to API', async () => {
            createStore();
            store.statusFilter = 'running';
            await store.loadExecutions();

            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ status: 'running' }),
                }),
            );
        });

        it('passes priority filter to API', async () => {
            createStore();
            store.priorityFilter = 'high';
            await store.loadExecutions();

            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ priority: 'high' }),
                }),
            );
        });

        it('passes user search to API', async () => {
            createStore();
            store.userSearch = 'user-42';
            await store.loadExecutions();

            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ user_id: 'user-42' }),
                }),
            );
        });

        it('omits undefined filter values when "all"', async () => {
            createStore();
            await store.loadExecutions();

            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({
                        status: undefined,
                        priority: undefined,
                        user_id: undefined,
                    }),
                }),
            );
        });
    });

    describe('updatePriority', () => {
        it('calls API and reloads data', async () => {
            createStore();
            await store.updatePriority('exec-1', 'high');

            expect(mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).toHaveBeenCalledWith({
                path: { execution_id: 'exec-1' },
                body: { priority: 'high' },
            });
            expect(mocks.toastSuccess).toHaveBeenCalledWith('Priority updated to high');
        });
    });

    describe('resetFilters', () => {
        it('resets all filters to defaults', () => {
            createStore();
            store.statusFilter = 'running';
            store.priorityFilter = 'high';
            store.userSearch = 'test';

            store.resetFilters();

            expect(store.statusFilter).toBe('all');
            expect(store.priorityFilter).toBe('all');
            expect(store.userSearch).toBe('');
        });
    });

    describe('auto-refresh', () => {
        it('fires loadData on interval', async () => {
            createStoreWithAutoRefresh();
            vi.clearAllMocks();
            setupDefaultMocks();

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledTimes(2);
        });

        it('stops on teardown', async () => {
            createStoreWithAutoRefresh();
            setupDefaultMocks();

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalled();

            const callsBefore = mocks.listExecutionsApiV1AdminExecutionsGet.mock.calls.length;
            teardown();
            vi.clearAllTimers();

            await vi.advanceTimersByTimeAsync(10000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet.mock.calls.length).toBe(callsBefore);
        });
    });

    describe('pagination', () => {
        it('passes pagination params to API', async () => {
            createStore();
            store.pagination.currentPage = 2;
            await store.loadExecutions();

            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({
                        skip: 20,
                        limit: 20,
                    }),
                }),
            );
        });
    });
});
