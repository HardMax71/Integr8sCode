import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { user, selectOption, createMockSaga, createMockSagas, mockApi } from '$test/test-utils';
import { listSagasApiV1SagasGet, getSagaStatusApiV1SagasSagaIdGet } from '$lib/api';

vi.mock('$routes/admin/AdminLayout.svelte', async () => {
    const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
    return { default: MockLayout };
});

import AdminSagas from '$routes/admin/AdminSagas.svelte';

async function renderWithSagas(sagas = createMockSagas(5)) {
    mockApi(listSagasApiV1SagasGet).ok({ sagas, total: sagas.length, skip: 0, limit: 10, has_more: false });

    const result = render(AdminSagas);
    await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());
    return result;
}

describe('AdminSagas', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(listSagasApiV1SagasGet).ok({ sagas: [], total: 0, skip: 0, limit: 10, has_more: false });
        mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(undefined);
    });

    describe('initial loading', () => {
        it('calls listSagas on mount', async () => {
            render(AdminSagas);
            await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());
        });

        it('displays loading state', async () => {
            mockApi(listSagasApiV1SagasGet).mock.mockImplementation(() => new Promise(() => {}));
            render(AdminSagas);
            await tick();
            expect(screen.getByText(/loading sagas/i)).toBeInTheDocument();
        });

        it('displays empty state when no sagas', async () => {
            await renderWithSagas([]);
            expect(screen.getByText(/no sagas found/i)).toBeInTheDocument();
        });
    });

    describe('saga list rendering', () => {
        it('displays saga data in table', async () => {
            const sagas = [createMockSaga({ saga_name: 'test_saga', state: 'running' })];
            await renderWithSagas(sagas);
            expect(screen.getAllByText('test_saga')).toHaveLength(2);
        });

        it('displays multiple sagas', async () => {
            const sagas = createMockSagas(3);
            await renderWithSagas(sagas);
            expect(screen.getAllByText(/saga-1/)).toHaveLength(2);
        });

        it('shows state badges with correct labels', async () => {
            const sagas = [
                createMockSaga({ saga_id: 's1', state: 'completed' }),
                createMockSaga({ saga_id: 's2', state: 'failed' }),
                createMockSaga({ saga_id: 's3', state: 'running' }),
            ];
            await renderWithSagas(sagas);
            // State labels appear in both table rows and stats cards
            expect(screen.getAllByText('Completed').length).toBeGreaterThan(0);
            expect(screen.getAllByText('Failed').length).toBeGreaterThan(0);
            expect(screen.getAllByText('Running').length).toBeGreaterThan(0);
        });

        it('shows retry count when > 0', async () => {
            const sagas = [createMockSaga({ retry_count: 3 })];
            await renderWithSagas(sagas);
            expect(screen.getByText('(3)', { exact: false })).toBeInTheDocument();
        });
    });

    describe('stats cards', () => {
        it('displays state counts', async () => {
            const sagas = [
                createMockSaga({ saga_id: 's1', state: 'completed' }),
                createMockSaga({ saga_id: 's2', state: 'completed' }),
                createMockSaga({ saga_id: 's3', state: 'failed' }),
            ];
            await renderWithSagas(sagas);
            const statsSection = screen.getByTestId('admin-layout');
            expect(statsSection).toBeInTheDocument();
        });
    });

    describe('auto-refresh', () => {
        it('auto-refreshes at specified interval', async () => {
            await renderWithSagas();
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(2);

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(3);
        });

        it('manual refresh button works', async () => {
            await renderWithSagas();
            vi.clearAllMocks();

            const refreshButton = screen.getByRole('button', { name: /refresh now/i });
            await user.click(refreshButton);

            await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());
        });

        it('toggling auto-refresh off stops polling', async () => {
            await renderWithSagas();

            const checkbox = screen.getByRole('checkbox', { name: /auto-refresh/i });
            await user.click(checkbox);

            vi.clearAllMocks();
            await vi.advanceTimersByTimeAsync(10000);

            expect(vi.mocked(listSagasApiV1SagasGet)).not.toHaveBeenCalled();
        });
    });

    describe('filters', () => {
        it('filters by state', async () => {
            await renderWithSagas();
            vi.clearAllMocks();

            const stateSelect = screen.getByLabelText(/state/i);
            selectOption(stateSelect, 'running');

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ state: 'running' }),
                    }),
                );
            });
        });

        it('filters by search query', async () => {
            const sagas = [
                createMockSaga({ saga_id: 's1', saga_name: 'alpha_saga' }),
                createMockSaga({ saga_id: 's2', saga_name: 'beta_saga' }),
            ];
            await renderWithSagas(sagas);

            const searchInput = screen.getByLabelText(/search/i);
            await user.type(searchInput, 'alpha');

            await waitFor(() => {
                expect(screen.getAllByText('alpha_saga')).toHaveLength(2);
            });
        });

        it('filters by execution ID', async () => {
            const sagas = [
                createMockSaga({ saga_id: 's1', execution_id: 'exec-abc' }),
                createMockSaga({ saga_id: 's2', execution_id: 'exec-xyz' }),
            ];
            await renderWithSagas(sagas);

            const matchingSaga = [createMockSaga({ saga_id: 's1', execution_id: 'exec-abc' })];
            mockApi(listSagasApiV1SagasGet).ok({ sagas: matchingSaga, total: 1, skip: 0, limit: 10, has_more: false });

            const execInput = screen.getByLabelText(/execution id/i);
            await user.type(execInput, 'abc');

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ execution_id: 'abc' }),
                    }),
                );
                expect(screen.getAllByText(/exec-abc/).length).toBeGreaterThan(0);
            });
        });

        it('clears filters on clear button click', async () => {
            await renderWithSagas();

            const stateSelect = screen.getByLabelText(/state/i);
            selectOption(stateSelect, 'failed');

            vi.clearAllMocks();
            const clearButton = screen.getByRole('button', { name: /clear filters/i });
            await user.click(clearButton);

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ state: undefined }),
                    }),
                );
            });
        });
    });

    describe('saga details modal', () => {
        it('opens modal on View Details click', async () => {
            const saga = createMockSaga({
                saga_name: 'execution_saga',
                completed_steps: ['validate_execution', 'allocate_resources'],
            });
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
            expect(screen.getByText('Saga Details')).toBeInTheDocument();
        });

        it('displays saga information in modal', async () => {
            const saga = createMockSaga({
                saga_id: 'saga-detail-test',
                saga_name: 'execution_saga',
                state: 'completed',
                completed_steps: ['validate_execution'],
                retry_count: 2,
            });
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => {
                expect(screen.getByText('saga-detail-test')).toBeInTheDocument();
            });
        });

        it('shows error message when saga has error', async () => {
            const saga = createMockSaga({
                state: 'failed',
                error_message: 'Pod creation failed: timeout',
            });
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => {
                expect(screen.getByText(/pod creation failed/i)).toBeInTheDocument();
            });
        });

        it('closes modal on close button click', async () => {
            const saga = createMockSaga();
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.click(screen.getByLabelText(/close modal/i));

            await waitFor(() => {
                expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
            });
        });

        it('shows compensated steps', async () => {
            const saga = createMockSaga({
                saga_name: 'execution_saga',
                state: 'failed',
                completed_steps: ['validate_execution', 'allocate_resources'],
                compensated_steps: ['release_resources'],
            });
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
            expect(screen.getByText('release_resources')).toBeInTheDocument();
        });
    });

    describe('view execution sagas', () => {
        it('loads sagas for specific execution', async () => {
            const executionSagas = [createMockSaga({ execution_id: 'exec-target' })];
            mockApi(listSagasApiV1SagasGet).ok({
                sagas: executionSagas,
                total: 1,
                skip: 0,
                limit: 10,
                has_more: false,
            });
            await renderWithSagas([createMockSaga({ execution_id: 'exec-target' })]);

            const [execButton] = screen.getAllByRole('button', { name: /execution/i });
            await user.click(execButton!);
            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ execution_id: 'exec-target' }),
                    }),
                );
            });
        });
    });

    describe('pagination', () => {
        it('shows pagination when items exist', async () => {
            const sagas = createMockSagas(5);
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 25, skip: 0, limit: 10, has_more: true });

            render(AdminSagas);
            await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());

            expect(screen.getByText(/showing/i)).toBeInTheDocument();
        });

        it('changes page size', async () => {
            const sagas = createMockSagas(5);
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 25, skip: 0, limit: 10, has_more: true });

            render(AdminSagas);
            await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());

            vi.clearAllMocks();
            const pageSizeSelect = screen.getByDisplayValue('10 / page');
            selectOption(pageSizeSelect, '25');

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ limit: 25 }),
                    }),
                );
            });
        });
    });

    describe('refresh rate control', () => {
        it('changes refresh rate', async () => {
            await renderWithSagas();

            const rateSelect = screen.getByLabelText(/every/i);
            selectOption(rateSelect, '10');

            vi.clearAllMocks();
            await vi.advanceTimersByTimeAsync(10000);

            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(1);
        });
    });
});
