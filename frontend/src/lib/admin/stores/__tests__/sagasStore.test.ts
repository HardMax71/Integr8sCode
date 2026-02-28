import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { effect_root } from 'svelte/internal/client';
import { createMockSaga } from '$test/test-utils';

const mocks = vi.hoisted(() => ({
    listSagasApiV1SagasGet: vi.fn(),
    unwrapOr: vi.fn((result: { data: unknown }, fallback: unknown) => result?.data ?? fallback),
}));

vi.mock('$lib/api', () => ({
    listSagasApiV1SagasGet: (...args: unknown[]) => mocks.listSagasApiV1SagasGet(...args),
}));

vi.mock('$lib/api-interceptors', () => ({
    unwrapOr: (result: { data: unknown }, fallback: unknown) => mocks.unwrapOr(result, fallback),
}));

const { createSagasStore } = await import('../sagasStore.svelte');

describe('SagasStore', () => {
    let store: ReturnType<typeof createSagasStore>;
    let teardown: () => void;

    beforeEach(() => {
        vi.clearAllMocks();
        mocks.listSagasApiV1SagasGet.mockResolvedValue({
            data: { sagas: [], total: 0 },
        });
    });

    function createStore() {
        teardown = effect_root(() => {
            store = createSagasStore();
        });
    }

    afterEach(() => {
        store?.cleanup();
        teardown?.();
    });

    describe('initial state', () => {
        it('starts with empty data and loading true', () => {
            createStore();
            expect(store.sagas).toEqual([]);
            expect(store.loading).toBe(true);
            expect(store.totalItems).toBe(0);
        });

        it('starts with default filters', () => {
            createStore();
            expect(store.stateFilter).toBe('');
            expect(store.executionIdFilter).toBe('');
            expect(store.searchQuery).toBe('');
        });
    });

    describe('loadSagas', () => {
        it('loads sagas from API', async () => {
            const sagas = [createMockSaga()];
            mocks.listSagasApiV1SagasGet.mockResolvedValue({
                data: { sagas, total: 1 },
            });

            createStore();
            await store.loadSagas();

            expect(store.sagas).toEqual(sagas);
            expect(store.totalItems).toBe(1);
            expect(store.loading).toBe(false);
        });

        it('handles empty API response', async () => {
            mocks.listSagasApiV1SagasGet.mockResolvedValue({ data: null });

            createStore();
            await store.loadSagas();

            expect(store.sagas).toEqual([]);
            expect(store.totalItems).toBe(0);
        });

        it('passes state filter to API', async () => {
            createStore();
            store.stateFilter = 'running';
            await store.loadSagas();

            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ state: 'running' }),
                }),
            );
        });

        it('passes pagination to API', async () => {
            createStore();
            store.pagination.currentPage = 3;
            await store.loadSagas();

            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ skip: 20, limit: 10 }),
                }),
            );
        });
    });

    describe('client-side filtering', () => {
        it('passes execution_id filter as query param', async () => {
            const sagas = [
                createMockSaga({ saga_id: 's1', execution_id: 'exec-abc' }),
            ];
            mocks.listSagasApiV1SagasGet.mockResolvedValue({
                data: { sagas, total: 1 },
            });

            createStore();
            store.executionIdFilter = 'exec-abc';
            await store.loadSagas();

            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ execution_id: 'exec-abc' }),
                }),
            );
            expect(store.sagas).toEqual(sagas);
        });

        it('filters by search query', async () => {
            const sagas = [
                createMockSaga({ saga_id: 's1', saga_name: 'alpha_saga' }),
                createMockSaga({ saga_id: 's2', saga_name: 'beta_saga' }),
            ];
            mocks.listSagasApiV1SagasGet.mockResolvedValue({
                data: { sagas, total: 2 },
            });

            createStore();
            store.searchQuery = 'alpha';
            await store.loadSagas();

            expect(store.sagas).toHaveLength(1);
            expect(store.sagas[0]!.saga_name).toBe('alpha_saga');
        });

        it('hasClientFilters is true when filters active', () => {
            createStore();
            expect(store.hasClientFilters).toBe(false);

            store.executionIdFilter = 'test';
            expect(store.hasClientFilters).toBe(true);
        });
    });

    describe('loadExecutionSagas', () => {
        it('sets filter and delegates to loadSagas with execution_id query param', async () => {
            const sagas = [createMockSaga({ execution_id: 'exec-target' })];
            mocks.listSagasApiV1SagasGet.mockResolvedValue({
                data: { sagas, total: 1 },
            });

            createStore();
            await store.loadExecutionSagas('exec-target');

            expect(store.executionIdFilter).toBe('exec-target');
            expect(store.pagination.currentPage).toBe(1);
            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ execution_id: 'exec-target' }),
                }),
            );
            expect(store.sagas).toEqual(sagas);
        });
    });

    describe('clearFilters', () => {
        it('resets all filters and reloads', async () => {
            createStore();
            store.stateFilter = 'failed';
            store.executionIdFilter = 'test';
            store.searchQuery = 'query';
            store.pagination.currentPage = 3;

            await store.clearFilters();

            expect(store.stateFilter).toBe('');
            expect(store.executionIdFilter).toBe('');
            expect(store.searchQuery).toBe('');
            expect(store.pagination.currentPage).toBe(1);
            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled();
        });
    });

    describe('auto-refresh', () => {
        it('fires loadSagas on interval', async () => {
            createStore();
            vi.clearAllMocks();

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledTimes(2);
        });

        it('passes execution_id on auto-refresh when filter is set', async () => {
            const sagas = [createMockSaga({ execution_id: 'exec-target' })];
            mocks.listSagasApiV1SagasGet.mockResolvedValue({
                data: { sagas, total: 1 },
            });

            createStore();
            await store.loadExecutionSagas('exec-target');
            vi.clearAllMocks();

            mocks.listSagasApiV1SagasGet.mockResolvedValue({
                data: { sagas, total: 1 },
            });

            await vi.advanceTimersByTimeAsync(5000);

            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ execution_id: 'exec-target' }),
                }),
            );
        });

        it('stops on cleanup', async () => {
            createStore();
            await vi.advanceTimersByTimeAsync(5000);
            expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled();

            const callsBefore = mocks.listSagasApiV1SagasGet.mock.calls.length;
            store.autoRefresh.enabled = false;
            store.cleanup();

            await vi.advanceTimersByTimeAsync(10000);
            expect(mocks.listSagasApiV1SagasGet.mock.calls.length).toBe(callsBefore);
        });
    });
});
