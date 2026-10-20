import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeSagaStatusResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { listSagasApiV1SagasGet, getSagaStatusApiV1SagasSagaIdGet, type SagaStatusResponse } from '#lib/api/index.ts';

import AdminSagas from '#routes/admin/sagas/+page.svelte';

async function renderWithSagas(sagas = Array.from({ length: 5 }, () => fakeSagaStatusResponse())) {
    mockApi(listSagasApiV1SagasGet).ok({ sagas, total: sagas.length, skip: 0, limit: 10, has_more: false });

    const result = renderWithQueryClient(AdminSagas);
    await screen.findByRole('table', { name: 'Sagas' });
    return result;
}

describe('AdminSagas', () => {
    beforeEach(() => {
        mockApi(listSagasApiV1SagasGet).ok({ sagas: [], total: 0, skip: 0, limit: 10, has_more: false });
        mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(fakeSagaStatusResponse());
    });

    describe('initial loading', () => {
        it('calls listSagas on mount', async () => {
            renderWithQueryClient(AdminSagas);
            await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());
        });

        it('displays loading state', async () => {
            mockApi(listSagasApiV1SagasGet).mock.mockImplementation(() => new Promise(() => {}));
            renderWithQueryClient(AdminSagas);
            await tick();
            expect(screen.getByText(/loading sagas/i)).toBeInTheDocument();
        });

        it('displays empty state when no sagas', async () => {
            renderWithQueryClient(AdminSagas);
            expect(await screen.findByText(/no sagas found/i)).toBeInTheDocument();
        });
    });

    describe('saga list rendering', () => {
        it('displays saga data in table', async () => {
            const sagas: SagaStatusResponse[] = [
                { ...fakeSagaStatusResponse(), saga_name: 'test_saga', state: 'running' },
            ];
            await renderWithSagas(sagas);
            expect(screen.getAllByText('test_saga')).toHaveLength(2);
        });

        it('displays multiple sagas', async () => {
            const sagas = Array.from({ length: 3 }, (_, i) => ({
                ...fakeSagaStatusResponse(),
                saga_id: `saga-${i + 1}`,
            }));
            await renderWithSagas(sagas);
            expect(screen.getAllByText(/saga-1/)).toHaveLength(2);
        });

        it('shows state badges with correct labels', async () => {
            const sagas: SagaStatusResponse[] = [
                { ...fakeSagaStatusResponse(), saga_id: 's1', state: 'completed' },
                { ...fakeSagaStatusResponse(), saga_id: 's2', state: 'failed' },
                { ...fakeSagaStatusResponse(), saga_id: 's3', state: 'running' },
            ];
            await renderWithSagas(sagas);
            // States appear in both table rows and stats cards
            expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
            expect(screen.getAllByText('failed').length).toBeGreaterThan(0);
            expect(screen.getAllByText('running').length).toBeGreaterThan(0);
        });

        it('shows retry count when > 0', async () => {
            const sagas = [{ ...fakeSagaStatusResponse(), retry_count: 3 }];
            await renderWithSagas(sagas);
            expect(screen.getAllByText('(Retry Count 3)').length).toBeGreaterThan(0);
        });
    });

    describe('stats cards', () => {
        it('displays state counts', async () => {
            const sagas: SagaStatusResponse[] = [
                { ...fakeSagaStatusResponse(), saga_id: 's1', state: 'completed' },
                { ...fakeSagaStatusResponse(), saga_id: 's2', state: 'completed' },
                { ...fakeSagaStatusResponse(), saga_id: 's3', state: 'failed' },
            ];
            await renderWithSagas(sagas);
            const terms = screen.getAllByRole('term').map((term) => term.textContent);
            expect(screen.getAllByRole('definition')[terms.indexOf('completed')]).toHaveTextContent('2');
        });
    });

    describe('auto-refresh', () => {
        it('auto-refreshes at specified interval', async () => {
            await renderWithSagas();
            vi.setTimerTickMode('manual');
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
            await user.selectOptions(stateSelect, 'running');

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ state: 'running' }),
                    }),
                );
            });
        });

        it('sends the search to the API, so it covers every page', async () => {
            const alpha = { ...fakeSagaStatusResponse(), saga_id: 's1', saga_name: 'alpha_saga' };
            await renderWithSagas([alpha, { ...fakeSagaStatusResponse(), saga_id: 's2', saga_name: 'beta_saga' }]);
            mockApi(listSagasApiV1SagasGet).ok({ sagas: [alpha], total: 1, skip: 0, limit: 10, has_more: false });

            await user.type(screen.getByLabelText(/search/i), 'alpha');

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenLastCalledWith(
                    expect.objectContaining({ query: expect.objectContaining({ search: 'alpha', skip: 0 }) }),
                );
                expect(screen.queryAllByText('beta_saga')).toHaveLength(0);
            });
            expect(screen.getAllByText('alpha_saga').length).toBeGreaterThan(0);
        });

        it('filters by execution ID', async () => {
            const sagas = [
                { ...fakeSagaStatusResponse(), saga_id: 's1', execution_id: 'exec-abc' },
                { ...fakeSagaStatusResponse(), saga_id: 's2', execution_id: 'exec-xyz' },
            ];
            await renderWithSagas(sagas);

            const matchingSaga = [{ ...fakeSagaStatusResponse(), saga_id: 's1', execution_id: 'exec-abc' }];
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
            await user.selectOptions(stateSelect, 'failed');

            vi.clearAllMocks();
            const clearButton = screen.getByRole('button', { name: /clear filters/i });
            await user.click(clearButton);

            await waitFor(() => {
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ state: null }),
                    }),
                );
            });
        });
    });

    describe('saga details modal', () => {
        it('opens modal on View Details click', async () => {
            const saga = {
                ...fakeSagaStatusResponse(),
                saga_name: 'execution_saga',
                completed_steps: ['validate_execution', 'create_pod'],
            };
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
            expect(screen.getByText('Saga Details')).toBeInTheDocument();
        });

        it('shows the execution from the details and closes them', async () => {
            const saga = { ...fakeSagaStatusResponse(), execution_id: 'exec-from-details' };
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            await user.click(within(screen.getByRole('table')).getByRole('button', { name: /view details/i }));
            await user.click(await within(await screen.findByRole('dialog')).findByText('exec-from-details'));

            await waitFor(() =>
                expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenLastCalledWith(
                    expect.objectContaining({ query: expect.objectContaining({ execution_id: 'exec-from-details' }) }),
                ),
            );
            await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        });

        it('displays saga information in modal', async () => {
            const saga: SagaStatusResponse = {
                ...fakeSagaStatusResponse(),
                saga_id: 'saga-detail-test',
                saga_name: 'execution_saga',
                state: 'completed',
                completed_steps: ['validate_execution'],
                retry_count: 2,
            };
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => {
                expect(screen.getByText('saga-detail-test')).toBeInTheDocument();
            });
        });

        it('shows error message when saga has error', async () => {
            const saga: SagaStatusResponse = {
                ...fakeSagaStatusResponse(),
                state: 'failed',
                error_message: 'Pod creation failed: timeout',
            };
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => {
                expect(screen.getByText(/pod creation failed/i)).toBeInTheDocument();
            });
        });

        it('closes modal on close button click', async () => {
            const saga = fakeSagaStatusResponse();
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: 'Close dialog' }));

            await waitFor(() => {
                expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
            });
        });

        it('shows compensated steps', async () => {
            const saga: SagaStatusResponse = {
                ...fakeSagaStatusResponse(),
                saga_name: 'execution_saga',
                state: 'failed',
                completed_steps: ['validate_execution', 'create_pod'],
                compensated_steps: ['delete_pod'],
            };
            mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
            await renderWithSagas([saga]);

            const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
            await user.click(viewBtn!);

            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
            expect(screen.getByText('delete_pod')).toBeInTheDocument();
        });
    });

    describe('view execution sagas', () => {
        it('loads sagas for specific execution', async () => {
            const executionSagas = [{ ...fakeSagaStatusResponse(), execution_id: 'exec-target' }];
            mockApi(listSagasApiV1SagasGet).ok({
                sagas: executionSagas,
                total: 1,
                skip: 0,
                limit: 10,
                has_more: false,
            });
            await renderWithSagas([{ ...fakeSagaStatusResponse(), execution_id: 'exec-target' }]);

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
            const sagas = Array.from({ length: 5 }, () => fakeSagaStatusResponse());
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 25, skip: 0, limit: 10, has_more: true });

            renderWithQueryClient(AdminSagas);
            expect(await screen.findByText(/showing/i)).toBeInTheDocument();
        });

        it('changes page size', async () => {
            const sagas = Array.from({ length: 5 }, () => fakeSagaStatusResponse());
            mockApi(listSagasApiV1SagasGet).ok({ sagas, total: 25, skip: 0, limit: 10, has_more: true });

            renderWithQueryClient(AdminSagas);
            await waitFor(() => expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalled());

            vi.clearAllMocks();
            const pageSizeSelect = screen.getByDisplayValue('10 / page');
            await user.selectOptions(pageSizeSelect, '25');

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
        it('polls at initial refresh rate', async () => {
            await renderWithSagas();
            vi.setTimerTickMode('manual');

            vi.clearAllMocks();
            await vi.advanceTimersByTimeAsync(5000);

            expect(vi.mocked(listSagasApiV1SagasGet)).toHaveBeenCalledTimes(1);
        });
    });
});
