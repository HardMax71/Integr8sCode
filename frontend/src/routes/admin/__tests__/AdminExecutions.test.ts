import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import {
    user,
    selectOption,
    createMockExecution,
    createMockExecutions,
    createMockQueueStatus,
    mockApi,
} from '$test/test-utils';
import {
    listExecutionsApiV1AdminExecutionsGet,
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut,
    getQueueStatusApiV1AdminExecutionsQueueGet,
} from '$lib/api';
import { toast } from 'svelte-sonner';

vi.mock('$routes/admin/AdminLayout.svelte', async () => {
    const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
    return { default: MockLayout };
});

import AdminExecutions from '$routes/admin/AdminExecutions.svelte';

async function renderWithExecutions(executions = createMockExecutions(5), queueStatus = createMockQueueStatus()) {
    mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
        executions,
        total: executions.length,
        limit: 20,
        skip: 0,
        has_more: false,
    });
    mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(queueStatus);

    const result = render(AdminExecutions);
    await waitFor(() => expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalled());
    return result;
}

describe('AdminExecutions', () => {
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
        mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).ok(null);
    });

    describe('initial loading', () => {
        it('calls API on mount', async () => {
            render(AdminExecutions);
            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalled();
                expect(vi.mocked(getQueueStatusApiV1AdminExecutionsQueueGet)).toHaveBeenCalled();
            });
        });

        it('displays empty state when no executions', async () => {
            await renderWithExecutions([]);
            expect(screen.getByText(/no executions found/i)).toBeInTheDocument();
        });

        it('displays execution data in table', async () => {
            const execs = [createMockExecution({ execution_id: 'exec-test-1', status: 'queued' })];
            await renderWithExecutions(execs);
            expect(screen.getByText('exec-test-1')).toBeInTheDocument();
        });
    });

    describe('queue status cards', () => {
        it('displays queue depth and active count', async () => {
            await renderWithExecutions(
                [],
                createMockQueueStatus({ queue_depth: 7, active_count: 3, max_concurrent: 10 }),
            );
            expect(screen.getByText('7')).toBeInTheDocument();
            expect(screen.getByText('3 / 10')).toBeInTheDocument();
        });

        it('displays by-priority breakdown', async () => {
            await renderWithExecutions([], createMockQueueStatus({ by_priority: { high: 2, normal: 5 } }));
            expect(screen.getByText(/high: 2/)).toBeInTheDocument();
            expect(screen.getByText(/normal: 5/)).toBeInTheDocument();
        });
    });

    describe('filters', () => {
        it('filters by status', async () => {
            await renderWithExecutions();
            vi.clearAllMocks();

            const statusSelect = screen.getByLabelText(/status/i);
            selectOption(statusSelect, 'running');

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

            const prioritySelect = screen.getByLabelText('Priority');
            selectOption(prioritySelect!, 'high');

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

            const statusSelect = screen.getByLabelText(/status/i);
            selectOption(statusSelect, 'running');

            vi.clearAllMocks();
            const resetButton = screen.getByRole('button', { name: /reset/i });
            await user.click(resetButton);

            await waitFor(() => {
                expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        query: expect.objectContaining({ status: undefined }),
                    }),
                );
            });
        });
    });

    describe('table rendering', () => {
        it('shows correct column headers', async () => {
            const execs = [createMockExecution()];
            await renderWithExecutions(execs);
            const headers = screen.getAllByRole('columnheader');
            const headerTexts = headers.map((h) => h.textContent?.trim());
            expect(headerTexts).toEqual(['ID', 'User', 'Language', 'Status', 'Priority', 'Created']);
        });

        it('shows language info', async () => {
            const execs = [createMockExecution({ lang: 'python', lang_version: '3.12' })];
            await renderWithExecutions(execs);
            expect(screen.getByText('python 3.12')).toBeInTheDocument();
        });

        it('shows status badge', async () => {
            const execs = [createMockExecution({ status: 'running' })];
            await renderWithExecutions(execs);
            expect(screen.getByText('running')).toBeInTheDocument();
        });
    });

    describe('priority update', () => {
        it('successful update shows success toast', async () => {
            const execs = [createMockExecution({ execution_id: 'e1', priority: 'normal' })];
            mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).ok({ ...execs[0], priority: 'high' });
            await renderWithExecutions(execs);

            const [prioritySelect] = screen.getAllByDisplayValue('normal');
            selectOption(prioritySelect!, 'high');

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
            const execs = [createMockExecution({ execution_id: 'e1', priority: 'normal' })];
            mockApi(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).err({ detail: 'Not found' });
            await renderWithExecutions(execs);

            const [prioritySelect] = screen.getAllByDisplayValue('normal');
            selectOption(prioritySelect!, 'critical');

            await waitFor(() => {
                expect(vi.mocked(updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { execution_id: 'e1' },
                        body: { priority: 'critical' },
                    }),
                );
            });
            expect(vi.mocked(toast.success)).not.toHaveBeenCalledWith(expect.anything());
        });
    });

    describe('auto-refresh', () => {
        it('auto-refreshes at 5s interval', async () => {
            await renderWithExecutions();
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
            const execs = createMockExecutions(5);
            mockApi(listExecutionsApiV1AdminExecutionsGet).ok({
                executions: execs,
                total: 50,
                limit: 20,
                skip: 0,
                has_more: true,
            });
            mockApi(getQueueStatusApiV1AdminExecutionsQueueGet).ok(createMockQueueStatus());

            render(AdminExecutions);
            await waitFor(() => expect(vi.mocked(listExecutionsApiV1AdminExecutionsGet)).toHaveBeenCalled());

            expect(screen.getByText(/showing/i)).toBeInTheDocument();
        });
    });
});
