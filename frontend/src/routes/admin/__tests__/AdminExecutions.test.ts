import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { user } from '$test/test-utils';

interface MockExecutionOverrides {
  execution_id?: string;
  script?: string;
  status?: string;
  lang?: string;
  lang_version?: string;
  priority?: string;
  user_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

const DEFAULT_EXECUTION = {
  execution_id: 'exec-1',
  script: 'print("hi")',
  status: 'queued',
  lang: 'python',
  lang_version: '3.11',
  priority: 'normal',
  user_id: 'user-1',
  created_at: '2024-01-15T10:30:00Z',
  updated_at: null as string | null,
};

const STATUSES = ['queued', 'scheduled', 'running', 'completed', 'failed', 'timeout', 'cancelled', 'error'];
const PRIORITIES = ['critical', 'high', 'normal', 'low', 'background'];

const createMockExecution = (overrides: MockExecutionOverrides = {}) => ({ ...DEFAULT_EXECUTION, ...overrides });

const createMockExecutions = (count: number) =>
  Array.from({ length: count }, (_, i) => createMockExecution({
    execution_id: `exec-${i + 1}`,
    status: STATUSES[i % STATUSES.length],
    priority: PRIORITIES[i % PRIORITIES.length],
    user_id: `user-${(i % 3) + 1}`,
    created_at: new Date(Date.now() - i * 60000).toISOString(),
  }));

const createMockQueueStatus = (overrides: Partial<{
  queue_depth: number;
  active_count: number;
  max_concurrent: number;
  by_priority: Record<string, number>;
}> = {}) => ({
  queue_depth: 5,
  active_count: 2,
  max_concurrent: 10,
  by_priority: { normal: 3, high: 2 },
  ...overrides,
});

const mocks = vi.hoisted(() => ({
  listExecutionsApiV1AdminExecutionsGet: vi.fn(),
  updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut: vi.fn(),
  getQueueStatusApiV1AdminExecutionsQueueGet: vi.fn(),
  addToast: vi.fn(),
}));

vi.mock('../../../lib/api', () => ({
  listExecutionsApiV1AdminExecutionsGet: (...args: unknown[]) => mocks.listExecutionsApiV1AdminExecutionsGet(...args),
  updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut: (...args: unknown[]) => mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut(...args),
  getQueueStatusApiV1AdminExecutionsQueueGet: (...args: unknown[]) => mocks.getQueueStatusApiV1AdminExecutionsQueueGet(...args),
}));

vi.mock('svelte-sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mocks.addToast('success', ...args),
    error: (...args: unknown[]) => mocks.addToast('error', ...args),
    warning: (...args: unknown[]) => mocks.addToast('warning', ...args),
    info: (...args: unknown[]) => mocks.addToast('info', ...args),
  },
}));

vi.mock('../../../lib/api-interceptors', async (importOriginal) => {
  const actual = await importOriginal() as Record<string, unknown>;
  return { ...actual };
});

vi.mock('../AdminLayout.svelte', async () => {
  const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
  return { default: MockLayout };
});

import AdminExecutions from '$routes/admin/AdminExecutions.svelte';

async function renderWithExecutions(
  executions = createMockExecutions(5),
  queueStatus = createMockQueueStatus(),
) {
  mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
    data: { executions, total: executions.length, limit: 20, skip: 0, has_more: false },
    error: null,
  });
  mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
    data: queueStatus,
    error: null,
  });

  const result = render(AdminExecutions);
  await tick();
  await waitFor(() => expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalled());
  return result;
}

describe('AdminExecutions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
      data: { executions: [], total: 0, limit: 20, skip: 0, has_more: false },
      error: null,
    });
    mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
      data: createMockQueueStatus(),
      error: null,
    });
    mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut.mockResolvedValue({
      data: null,
      error: null,
    });
  });


  describe('initial loading', () => {
    it('calls API on mount', async () => {
      render(AdminExecutions);
      await tick();
      await waitFor(() => {
        expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalled();
        expect(mocks.getQueueStatusApiV1AdminExecutionsQueueGet).toHaveBeenCalled();
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
      await renderWithExecutions([], createMockQueueStatus({ queue_depth: 7, active_count: 3, max_concurrent: 10 }));
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
      await user.selectOptions(statusSelect, 'running');

      await waitFor(() => {
        expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
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
      await user.selectOptions(prioritySelect!, 'high');

      await waitFor(() => {
        expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
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
        expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
          expect.objectContaining({
            query: expect.objectContaining({ user_id: 'user-42' }),
          }),
        );
      });
    });

    it('reset button clears all filters', async () => {
      await renderWithExecutions();

      const statusSelect = screen.getByLabelText(/status/i);
      await user.selectOptions(statusSelect, 'running');

      vi.clearAllMocks();
      const resetButton = screen.getByRole('button', { name: /reset/i });
      await user.click(resetButton);

      await waitFor(() => {
        expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledWith(
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
      const headerTexts = headers.map(h => h.textContent?.trim());
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
      mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut.mockResolvedValue({
        data: { ...execs[0], priority: 'high' },
        error: null,
      });
      await renderWithExecutions(execs);

      const [prioritySelect] = screen.getAllByDisplayValue('normal');
      await user.selectOptions(prioritySelect!, 'high');

      await waitFor(() => {
        expect(mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).toHaveBeenCalledWith(
          expect.objectContaining({
            path: { execution_id: 'e1' },
            body: { priority: 'high' },
          }),
        );
      });

      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('success', expect.stringContaining('high'));
      });
    });

    it('failed update calls API and does not show success toast', async () => {
      const execs = [createMockExecution({ execution_id: 'e1', priority: 'normal' })];
      mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut.mockResolvedValue({
        data: undefined,
        error: { detail: 'Not found' },
      });
      await renderWithExecutions(execs);

      const [prioritySelect] = screen.getAllByDisplayValue('normal');
      await user.selectOptions(prioritySelect!, 'critical');

      await waitFor(() => {
        expect(mocks.updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut).toHaveBeenCalledWith(
          expect.objectContaining({
            path: { execution_id: 'e1' },
            body: { priority: 'critical' },
          }),
        );
      });
      expect(mocks.addToast).not.toHaveBeenCalledWith('success', expect.anything());
    });
  });

  describe('auto-refresh', () => {
    it('auto-refreshes at 5s interval', async () => {
      await renderWithExecutions();
      const initialCalls = mocks.listExecutionsApiV1AdminExecutionsGet.mock.calls.length;

      await vi.advanceTimersByTimeAsync(5000);
      expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledTimes(initialCalls + 1);

      await vi.advanceTimersByTimeAsync(5000);
      expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalledTimes(initialCalls + 2);
    });

    it('manual refresh button calls loadData', async () => {
      await renderWithExecutions();
      vi.clearAllMocks();

      const refreshButton = screen.getByRole('button', { name: /refresh/i });
      await user.click(refreshButton);

      await waitFor(() => {
        expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalled();
        expect(mocks.getQueueStatusApiV1AdminExecutionsQueueGet).toHaveBeenCalled();
      });
    });
  });

  describe('pagination', () => {
    it('shows pagination when totalPages > 1', async () => {
      const execs = createMockExecutions(5);
      mocks.listExecutionsApiV1AdminExecutionsGet.mockResolvedValue({
        data: { executions: execs, total: 50, limit: 20, skip: 0, has_more: true },
        error: null,
      });
      mocks.getQueueStatusApiV1AdminExecutionsQueueGet.mockResolvedValue({
        data: createMockQueueStatus(),
        error: null,
      });

      render(AdminExecutions);
      await tick();
      await waitFor(() => expect(mocks.listExecutionsApiV1AdminExecutionsGet).toHaveBeenCalled());

      expect(screen.getByText(/showing/i)).toBeInTheDocument();
    });
  });
});
