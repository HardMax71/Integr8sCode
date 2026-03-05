import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { effect_root } from 'svelte/internal/client';
import { createMockSaga, mockApi } from '$test/test-utils';
import { listSagasApiV1SagasGet } from '$lib/api';
import { createSagasStore } from '$lib/admin/stores/sagasStore.svelte';

describe('SagasStore', () => {
    let store: ReturnType<typeof createSagasStore>;
    let teardown: () => void;

    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(listSagasApiV1SagasGet).ok({ sagas: [], total: 0 });
    });

    function createStore() {
        teardown = effect_root(() => {
            store = createSagasStore();
        });
    }

    afterEach(() => {
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
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 1 });

            createStore();
            await store.loadSagas();

            expect(store.sagas).toEqual(sagas);
            expect(store.totalItems).toBe(1);
            expect(store.loading).toBe(false);
        });

        it('handles empty API response', async () => {
            mockApi(listSagasApiV1SagasGet).ok(undefined);

            createStore();
            await store.loadSagas();

            expect(store.sagas).toEqual([]);
            expect(store.totalItems).toBe(0);
        });

        it('passes state filter to API', async () => {
            createStore();
            store.stateFilter = 'running';
            await store.loadSagas();

            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ state: 'running' }),
                }),
            );
        });

        it('passes pagination to API', async () => {
            createStore();
            store.pagination.currentPage = 3;
            await store.loadSagas();

            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ skip: 20, limit: 10 }),
                }),
            );
        });
    });

    describe('client-side filtering', () => {
        it('passes execution_id filter as query param', async () => {
            const sagas = [createMockSaga({ saga_id: 's1', execution_id: 'exec-abc' })];
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 1 });

            createStore();
            store.executionIdFilter = 'exec-abc';
            await store.loadSagas();

            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
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
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 2 });

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
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 1 });

            createStore();
            await store.loadExecutionSagas('exec-target');

            expect(store.executionIdFilter).toBe('exec-target');
            expect(store.pagination.currentPage).toBe(1);
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
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
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled();
        });
    });

    describe('auto-refresh', () => {
        it('fires loadSagas on interval', async () => {
            createStore();
            vi.clearAllMocks();

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(2);
        });

        it('passes execution_id on auto-refresh when filter is set', async () => {
            const sagas = [createMockSaga({ execution_id: 'exec-target' })];
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 1 });

            createStore();
            await store.loadExecutionSagas('exec-target');
            vi.clearAllMocks();

            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 1 });

            await vi.advanceTimersByTimeAsync(5000);

            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: expect.objectContaining({ execution_id: 'exec-target' }),
                }),
            );
        });

        it('stops when refreshEnabled set to false', async () => {
            createStore();
            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled();

            const callsBefore = vi.mocked(listSagasApiV1SagasGet).mock.calls.length;
            store.refreshEnabled = false;

            await vi.advanceTimersByTimeAsync(10000);
            expect(vi.mocked(listSagasApiV1SagasGet).mock.calls.length).toBe(callsBefore);
        });
    });
});
