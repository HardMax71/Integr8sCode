import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createInQueryContext, createMockExecution, createMockQueueStatus, mockApi } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import {
    listExecutionsApiV1AdminExecutionsGet,
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut,
    getQueueStatusApiV1AdminExecutionsQueueGet,
} from '#lib/api/index.ts';
import { createExecutionsStore } from '#lib/admin/stores/executionsStore.svelte.ts';

const listExecutions = vi.mocked(listExecutionsApiV1AdminExecutionsGet);
const getQueueStatus = vi.mocked(getQueueStatusApiV1AdminExecutionsQueueGet);
const updatePriority = vi.mocked(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut);

function lastQuery() {
    return listExecutions.mock.lastCall?.[0]?.query;
}

describe('ExecutionsStore', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
            executions: [],
            total: 0,
            limit: 20,
            skip: 0,
            has_more: false,
        });
        mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(createMockQueueStatus());
        mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).ok(createMockExecution());
    });

    function createStore() {
        return createInQueryContext(createExecutionsStore);
    }

    describe('initial state', () => {
        it('starts with empty data and default filters', () => {
            const { value: store } = createStore();
            expect(store.executions).toEqual([]);
            expect(store.total).toBe(0);
            expect(store.queueStatus.data).toBeUndefined();
            expect(store.statusFilter).toBe('all');
            expect(store.priorityFilter).toBe('all');
            expect(store.userSearch).toBe('');
            expect(store.pagination.pageIndex).toBe(0);
        });
    });

    describe('queries', () => {
        it('loads executions and queue status', async () => {
            const execs = [createMockExecution()];
            mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
                executions: execs,
                total: 1,
                limit: 20,
                skip: 0,
                has_more: false,
            });

            const { value: store } = createStore();

            await vi.waitFor(() => expect(store.executions).toEqual(execs));
            expect(store.total).toBe(1);
            await vi.waitFor(() => expect(store.queueStatus.data).toEqual(createMockQueueStatus()));
        });

        it('leaves "all" filters out of the request', async () => {
            createStore();
            await vi.waitFor(() =>
                expect(lastQuery()).toEqual({
                    limit: 20,
                    skip: 0,
                    status: undefined,
                    priority: undefined,
                    user_id: undefined,
                }),
            );
        });

        it('sends the filters and the page to the API', async () => {
            const { value: store } = createStore();
            store.statusFilter = 'running';
            store.priorityFilter = 'high';
            store.userSearch = 'user-42';
            store.pagination = { pageIndex: 1, pageSize: 20 };

            await vi.waitFor(() =>
                expect(lastQuery()).toEqual({
                    limit: 20,
                    skip: 20,
                    status: 'running',
                    priority: 'high',
                    user_id: 'user-42',
                }),
            );
        });

        it('goes back to the first page when a filter changes', () => {
            const { value: store } = createStore();
            store.pagination = { pageIndex: 2, pageSize: 20 };
            store.statusFilter = 'failed';
            expect(store.pagination.pageIndex).toBe(0);

            store.pagination = { pageIndex: 2, pageSize: 20 };
            store.priorityFilter = 'low';
            expect(store.pagination.pageIndex).toBe(0);

            store.pagination = { pageIndex: 2, pageSize: 20 };
            store.userSearch = 'u';
            expect(store.pagination.pageIndex).toBe(0);
        });
    });

    describe('updatePriority', () => {
        it('calls the API, toasts and refetches the list and the queue', async () => {
            const { value: store } = createStore();
            await vi.waitFor(() => expect(store.list.isSuccess).toBe(true));
            listExecutions.mockClear();
            getQueueStatus.mockClear();

            await store.updatePriority.mutateAsync({ path: { execution_id: 'exec-1' }, body: { priority: 'high' } });

            expect(updatePriority).toHaveBeenCalledWith(
                expect.objectContaining({ path: { execution_id: 'exec-1' }, body: { priority: 'high' } }),
            );
            expect(vi.mocked(toast.success)).toHaveBeenCalledWith('Priority updated to high');
            expect(listExecutions).toHaveBeenCalledTimes(1);
            expect(getQueueStatus).toHaveBeenCalledTimes(1);
        });

        it('does not toast success when the API fails', async () => {
            mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).err({ detail: 'Not found' });
            const { value: store } = createStore();

            await expect(
                store.updatePriority.mutateAsync({ path: { execution_id: 'e1' }, body: { priority: 'low' } }),
            ).rejects.toEqual({ detail: 'Not found' });

            expect(vi.mocked(toast.success)).not.toHaveBeenCalled();
        });
    });

    describe('resetFilters', () => {
        it('resets all filters to defaults', () => {
            const { value: store } = createStore();
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
        it('refetches every 5 seconds', async () => {
            createStore();
            await vi.waitFor(() => expect(listExecutions).toHaveBeenCalledTimes(1));

            await vi.advanceTimersByTimeAsync(5000);
            expect(listExecutions).toHaveBeenCalledTimes(2);
            expect(getQueueStatus).toHaveBeenCalledTimes(2);

            await vi.advanceTimersByTimeAsync(5000);
            expect(listExecutions).toHaveBeenCalledTimes(3);
        });

        it('stops when the page unmounts', async () => {
            const { unmount } = createStore();
            await vi.waitFor(() => expect(listExecutions).toHaveBeenCalledTimes(1));

            unmount();
            await vi.advanceTimersByTimeAsync(10000);

            expect(listExecutions).toHaveBeenCalledTimes(1);
        });
    });
});
