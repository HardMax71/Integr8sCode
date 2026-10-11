import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createInQueryContext, createMockSaga, mockApi } from '#test/test-utils.ts';
import { getSagaStatusApiV1SagasSagaIdGet, listSagasApiV1SagasGet } from '#lib/api/index.ts';
import { createSagasStore } from '#lib/admin/stores/sagasStore.svelte.ts';

const listSagas = vi.mocked(listSagasApiV1SagasGet);

function lastQuery() {
    return listSagas.mock.lastCall?.[0]?.query;
}

describe('SagasStore', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(listSagasApiV1SagasGet).ok({ sagas: [], total: 0, skip: 0, limit: 10, has_more: false });
    });

    function createStore() {
        return createInQueryContext(createSagasStore);
    }

    describe('initial state', () => {
        it('starts with empty data, default filters and the first page', () => {
            const { value: store } = createStore();
            expect(store.sagas).toEqual([]);
            expect(store.totalItems).toBe(0);
            expect(store.list.isPending).toBe(true);
            expect(store.stateFilter).toBe('');
            expect(store.executionIdFilter).toBe('');
            expect(store.searchQuery).toBe('');
            expect(store.currentPage).toBe(1);
        });
    });

    describe('list query', () => {
        it('loads sagas from the API', async () => {
            const sagas = [createMockSaga()];
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 1, skip: 0, limit: 10, has_more: false });

            const { value: store } = createStore();

            await vi.waitFor(() => expect(store.sagas).toEqual(sagas));
            expect(store.totalItems).toBe(1);
            expect(store.list.isPending).toBe(false);
        });

        it('sends every filter to the API, search included, so it covers all pages', async () => {
            const { value: store } = createStore();
            store.stateFilter = 'running';
            store.executionIdFilter = 'exec-abc';
            store.searchQuery = 'alpha';

            await vi.waitFor(() =>
                expect(lastQuery()).toEqual({
                    state: 'running',
                    execution_id: 'exec-abc',
                    search: 'alpha',
                    limit: 10,
                    skip: 0,
                }),
            );
        });

        it('sends the page as skip and limit', async () => {
            const { value: store } = createStore();
            store.currentPage = 3;

            await vi.waitFor(() => expect(lastQuery()).toMatchObject({ skip: 20, limit: 10 }));
        });

        it('goes back to the first page when a filter changes', () => {
            const { value: store } = createStore();
            store.currentPage = 4;
            store.stateFilter = 'failed';
            expect(store.currentPage).toBe(1);

            store.currentPage = 4;
            store.executionIdFilter = 'exec-1';
            expect(store.currentPage).toBe(1);

            store.currentPage = 4;
            store.searchQuery = 'alpha';
            expect(store.currentPage).toBe(1);
        });
    });

    describe('clearFilters', () => {
        it('resets all filters and the page', () => {
            const { value: store } = createStore();
            store.stateFilter = 'failed';
            store.executionIdFilter = 'test';
            store.searchQuery = 'query';
            store.currentPage = 3;

            store.clearFilters();

            expect(store.stateFilter).toBe('');
            expect(store.executionIdFilter).toBe('');
            expect(store.searchQuery).toBe('');
            expect(store.currentPage).toBe(1);
        });
    });

    describe('openDetails', () => {
        it('loads the saga into selectedSaga', async () => {
            const saga = createMockSaga({ saga_id: 's1' });
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            const { value: store } = createStore();

            await store.openDetails('s1');

            expect(store.selectedSaga).toEqual(saga);
            expect(vi.mocked(getSagaStatusApiV1SagasSagaIdGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { saga_id: 's1' } }),
            );
        });

        it('leaves selectedSaga empty when the load fails', async () => {
            mockApi(getSagaStatusApiV1SagasSagaIdGet).err({ detail: 'Saga not found' });
            const { value: store } = createStore();

            await store.openDetails('missing');

            expect(store.selectedSaga).toBeNull();
        });
    });

    describe('auto-refresh', () => {
        it('refetches at the refresh rate', async () => {
            createStore();
            await vi.waitFor(() => expect(listSagas).toHaveBeenCalledTimes(1));

            await vi.advanceTimersByTimeAsync(5000);
            expect(listSagas).toHaveBeenCalledTimes(2);

            await vi.advanceTimersByTimeAsync(5000);
            expect(listSagas).toHaveBeenCalledTimes(3);
        });

        it('keeps the filters on refetch', async () => {
            const { value: store } = createStore();
            store.executionIdFilter = 'exec-target';
            await vi.waitFor(() => expect(lastQuery()).toMatchObject({ execution_id: 'exec-target' }));
            listSagas.mockClear();

            await vi.advanceTimersByTimeAsync(5000);

            expect(listSagas).toHaveBeenCalledTimes(1);
            expect(lastQuery()).toMatchObject({ execution_id: 'exec-target' });
        });

        it('stops when refreshEnabled is set to false', async () => {
            const { value: store } = createStore();
            await vi.waitFor(() => expect(listSagas).toHaveBeenCalledTimes(1));

            store.refreshEnabled = false;
            await vi.advanceTimersByTimeAsync(10000);

            expect(listSagas).toHaveBeenCalledTimes(1);
        });

        it('stops when the page unmounts', async () => {
            const { unmount } = createStore();
            await vi.waitFor(() => expect(listSagas).toHaveBeenCalledTimes(1));

            unmount();
            await vi.advanceTimersByTimeAsync(10000);

            expect(listSagas).toHaveBeenCalledTimes(1);
        });
    });
});
