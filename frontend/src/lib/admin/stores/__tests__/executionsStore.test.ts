import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { effect_root } from 'svelte/internal/client';

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

const createMockExecution = (overrides: Record<string, unknown> = {}) => ({
    execution_id: 'exec-1',
    script: 'print("hi")',
    status: 'queued',
    lang: 'python',
    lang_version: '3.11',
    priority: 'normal',
    user_id: 'user-1',
    created_at: '2024-01-15T10:30:00Z',
    updated_at: null,
    ...overrides,
});

const createMockQueueStatus = (overrides: Record<string, unknown> = {}) => ({
    queue_depth: 5,
    active_count: 2,
    max_concurrent: 10,
    by_priority: { normal: 3, high: 2 },
    ...overrides,
});

describe('ExecutionsStore', () => {
    let store: ReturnType<typeof createExecutionsStore>;
    let teardown: () => void;

    beforeEach(() => {
        vi.clearAllMocks();
        mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
            data: { executions: [], total: 0, limit: 20, skip: 0, has_more: false },
        });
        mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
            data: createMockQueueStatus(),
        });
        mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut.mockResolvedValue({
            data: null,
        });
    });

    function createStore() {
        teardown = effect_root(() => {
            store = createExecutionsStore();
        });
    }

    afterEach(() => {
        store?.cleanup();
        teardown?.();
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
            const execs = [createMockExecution()];
            mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
                data: { executions: execs, total: 1 },
            });
            mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
                data: createMockQueueStatus(),
            });

            createStore();
            await store.loadData();

            expect(store.executions).toEqual(execs);
            expect(store.total).toBe(1);
            expect(store.queueStatus).toEqual(createMockQueueStatus());
        });

        it('handles empty API response', async () => {
            mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({ data: null });

            createStore();
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
            createStore();
            vi.clearAllMocks();

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledTimes(2);
        });

        it('stops on cleanup', async () => {
            createStore();
            // Verify interval is running
            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalled();

            const callsBefore = mocks.listExecutionsApiV1AdminExecutionsGet.mock.calls.length;
            store.autoRefresh.enabled = false;
            store.cleanup();

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
