import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeAdminExecutionResponse, fakeQueueStatusResponse } from '#lib/api/@faker-js/faker.gen.ts';
import {
    listExecutionsApiV1AdminExecutionsGet,
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut,
    getQueueStatusApiV1AdminExecutionsQueueGet,
    type AdminExecutionResponse,
} from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';
import { queryClient } from '#lib/query-client.ts';
import { toast } from 'svelte-sonner';

import AdminExecutions from '#routes/admin/executions/+page.svelte';

async function renderWithExecutions(
    executions = Array.from({ length: 5 }, () => fakeAdminExecutionResponse()),
    queueStatus = fakeQueueStatusResponse(),
) {
    mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
        executions,
        total: executions.length,
        limit: 20,
        skip: 0,
        has_more: false,
    });
    mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(queueStatus);

    const result = renderWithQueryClient(AdminExecutions);
    await screen.findByRole('table', { name: 'Executions' });
    return result;
}

const executionsTable = () => screen.getByRole('table', { name: 'Executions' });

describe('AdminExecutions', () => {
    beforeEach(() => {
        mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
            executions: [],
            total: 0,
            limit: 20,
            skip: 0,
            has_more: false,
        });
        mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(fakeQueueStatusResponse());
        mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).ok(fakeAdminExecutionResponse());
    });

    describe('initial loading', () => {
        it('calls API on mount', async () => {
            renderWithQueryClient(AdminExecutions);
            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalled();
                expect(vi.mocked(getQueueStatusApiV1AdminExecutionsQueueGet)).toHaveBeenCalled();
            });
        });

        it('displays empty state when no executions', async () => {
            renderWithQueryClient(AdminExecutions);
            expect(await screen.findByText(/no executions found/i)).toBeInTheDocument();
        });

        it('displays execution data in table', async () => {
            const execs: AdminExecutionResponse[] = [
                { ...fakeAdminExecutionResponse(), execution_id: 'exec-test-1', status: 'queued' },
            ];
            await renderWithExecutions(execs);
            expect(within(executionsTable()).getByText('exec-test-1')).toBeInTheDocument();
        });
    });

    describe('queue status cards', () => {
        it('displays queue depth and active count', async () => {
            mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok({
                ...fakeQueueStatusResponse(),
                queue_depth: 7,
                active_count: 3,
                max_concurrent: 10,
            });
            renderWithQueryClient(AdminExecutions);
            expect(await screen.findByText('7')).toBeInTheDocument();
            expect(screen.getByText('3 / 10')).toBeInTheDocument();
        });

        it('displays by-priority breakdown', async () => {
            mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok({
                ...fakeQueueStatusResponse(),
                by_priority: { high: 2, normal: 5 },
            });
            renderWithQueryClient(AdminExecutions);
            expect(await screen.findByText(/high: 2/)).toBeInTheDocument();
            expect(screen.getByText(/normal: 5/)).toBeInTheDocument();
        });
    });

    describe('filters', () => {
        it('filters by status', async () => {
            await renderWithExecutions();
            vi.clearAllMocks();

            const statusSelect = screen.getByLabelText(/status/i);
            await user.selectOptions(statusSelect, 'running');

            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ status: 'running' }),
                    }),
                );
            });
        });

        it('filters by priority', async () => {
            await renderWithExecutions();
            vi.clearAllMocks();

            await user.selectOptions(screen.getByLabelText('Priority'), 'high');

            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ priority: 'high' }),
                    }),
                );
            });
        });

        it('filters by user ID', async () => {
            await renderWithExecutions();
            vi.clearAllMocks();

            const userInput = screen.getByLabelText(/user id/i);
            await user.type(userInput, 'user-42');

            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ user_id: 'user-42' }),
                    }),
                );
            });
        });

        it('reset button clears all filters', async () => {
            await renderWithExecutions();

            await user.selectOptions(screen.getByLabelText(/status/i), 'running');

            vi.clearAllMocks();
            const resetButton = screen.getByRole('button', { name: /reset/i });
            await user.click(resetButton);

            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ status: null }),
                    }),
                );
            });
        });
    });

    describe('table rendering', () => {
        it('shows correct column headers', async () => {
            const execs = [fakeAdminExecutionResponse()];
            await renderWithExecutions(execs);
            const headers = screen.getAllByRole('columnheader');
            const headerTexts = headers.map((h) => h.textContent?.trim());
            expect(headerTexts).toEqual(
                ['execution_id', 'user_id', 'lang', 'status', 'priority', 'created_at'].map(fieldTitle),
            );
        });

        it('shows language info', async () => {
            const execs = [{ ...fakeAdminExecutionResponse(), lang: 'python', lang_version: '3.12' }];
            await renderWithExecutions(execs);
            expect(within(executionsTable()).getByText('python 3.12')).toBeInTheDocument();
        });

        it('shows status badge', async () => {
            const execs: AdminExecutionResponse[] = [{ ...fakeAdminExecutionResponse(), status: 'running' }];
            await renderWithExecutions(execs);
            expect(within(executionsTable()).getByText('running')).toHaveClass('badge', 'badge-info');
        });
    });

    describe('priority update', () => {
        it('successful update shows success toast', async () => {
            const execs: AdminExecutionResponse[] = [
                { ...fakeAdminExecutionResponse(), execution_id: 'e1', priority: 'normal' },
            ];
            mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).ok({
                ...fakeAdminExecutionResponse(),
                execution_id: 'e1',
                priority: 'high',
            });
            await renderWithExecutions(execs);

            const [prioritySelect] = screen.getAllByDisplayValue('normal');
            await user.selectOptions(prioritySelect!, 'high');

            await waitFor(() => {
                expect(vi.mocked(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { execution_id: 'e1' },
                        body: { priority: 'high' },
                    }),
                );
            });

            await waitFor(() => {
                expect(vi.mocked(toast.success)).toHaveBeenCalledWith(expect.stringContaining('high'));
            });
        });

        it('failed update calls API and does not show success toast', async () => {
            const execs: AdminExecutionResponse[] = [
                { ...fakeAdminExecutionResponse(), execution_id: 'e1', priority: 'normal' },
            ];
            mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).err({ status: 404, detail: 'Not found' });
            await renderWithExecutions(execs);

            const [prioritySelect] = screen.getAllByDisplayValue('normal');
            await user.selectOptions(prioritySelect!, 'critical');

            await waitFor(() => {
                expect(vi.mocked(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { execution_id: 'e1' },
                        body: { priority: 'critical' },
                    }),
                );
            });
            await waitFor(() => expect(queryClient.getMutationCache().getAll()[0]?.state.status).toBe('error'));
            expect(vi.mocked(toast.success)).not.toHaveBeenCalled();
        });
    });

    describe('auto-refresh', () => {
        it('auto-refreshes at 5s interval', async () => {
            await renderWithExecutions();
            vi.setTimerTickMode('manual');
            const initialCalls = vi.mocked(listExecutionsApiV1AdminExecutionsGet).mock.calls.length;

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledTimes(initialCalls + 1);

            await vi.advanceTimersByTimeAsync(5000);
            expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledTimes(initialCalls + 2);
        });

        it('manual refresh button calls loadData', async () => {
            await renderWithExecutions();
            vi.clearAllMocks();

            const refreshButton = screen.getByRole('button', { name: /refresh/i });
            await user.click(refreshButton);

            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalled();
                expect(vi.mocked(getQueueStatusApiV1AdminExecutionsQueueGet)).toHaveBeenCalled();
            });
        });
    });

    describe('pagination', () => {
        it('shows pagination when totalPages > 1', async () => {
            const execs = Array.from({ length: 5 }, () => fakeAdminExecutionResponse());
            mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
                executions: execs,
                total: 50,
                limit: 20,
                skip: 0,
                has_more: true,
            });
            mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(fakeQueueStatusResponse());

            renderWithQueryClient(AdminExecutions);
            expect(await screen.findByText(/showing/i)).toBeInTheDocument();
        });
    });
});
