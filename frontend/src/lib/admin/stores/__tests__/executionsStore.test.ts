import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { effect_root } from 'svelte/internal/client';
import { createMockExecution, createMockQueueStatus, mockApi } from '$test/test-utils';
import { toast } from 'svelte-sonner';
import {
    listExecutionsApiV1AdminExecutionsGet,
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut,
    getQueueStatusApiV1AdminExecutionsQueueGet,
} from '$lib/api';
import { createExecutionsStore } from '$lib/admin/stores/executionsStore.svelte';

function setupDefaultMocks() {
    mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
        executions: [],
        total: 0,
        limit: 20,
        skip: 0,
        has_more: false,
    });
    mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(createMockQueueStatus());
    mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).ok(null);
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
            mockApi(listExecutionsApiV1AdminExecutionsGet).ok({ executions: execs, total: 1 });
            mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(createMockQueueStatus());

            await store.loadData();

            expect(store.executions).toEqual(execs);
            expect(store.total).toBe(1);
            expect(store.queueStatus).toEqual(createMockQueueStatus());
        });

        it('handles empty API response', async () => {
            createStore();
            mockApi(listExecutionsApiV1AdminExecutionsGet).ok(undefined);

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

            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ status: 'running' }),
                }),
            );
        });

        it('passes priority filter to API', async () => {
            createStore();
            store.priorityFilter = 'high';
            await store.loadExecutions();

            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ priority: 'high' }),
                }),
            );
        });

        it('passes user search to API', async () => {
            createStore();
            store.userSearch = 'user-42';
            await store.loadExecutions();

            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ user_id: 'user-42' }),
                }),
            );
        });

        it('omits undefined filter values when "all"', async () => {
            createStore();
            await store.loadExecutions();

            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
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

            expect(vi.mocked(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut)).toHaveBeenCalledWith({
                path: { execution_id: 'exec-1' },
                body: { priority: 'high' },
            });
            expect(vi.mocked(toast.success)).toHaveBeenCalledWith('Priority updated to high');
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
            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledTimes(2);
        });

        it('stops on teardown', async () => {
            createStoreWithAutoRefresh();
            setupDefaultMocks();

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalled();

            const callsBefore = vi.mocked(listExecutionsApiV1AdminExecutionsGet).mock.calls.length;
            teardown();
            vi.clearAllTimers();

            await vi.advanceTimersByTimeAsync(10000);
            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet).mock.calls.length).toBe(callsBefore);
        });
    });

    describe('pagination', () => {
        it('passes pagination params to API', async () => {
            createStore();
            store.pagination.currentPage = 2;
            await store.loadExecutions();

            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
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
