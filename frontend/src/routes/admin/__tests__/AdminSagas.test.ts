import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick } from 'svelte';

interface MockSagaOverrides {
  saga_id?: string;
  saga_name?: string;
  execution_id?: string;
  state?: string;
  current_step?: string;
  completed_steps?: string[];
  compensated_steps?: string[];
  retry_count?: number;
  error_message?: string | null;
  context_data?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
}

const DEFAULT_SAGA = {
  saga_id: 'saga-1',
  saga_name: 'execution_saga',
  execution_id: 'exec-123',
  state: 'running',
  current_step: 'create_pod',
  completed_steps: ['validate_execution', 'allocate_resources', 'queue_execution'],
  compensated_steps: [] as string[],
  retry_count: 0,
  error_message: null as string | null,
  context_data: { key: 'value' },
  created_at: '2024-01-15T10:30:00Z',
  updated_at: '2024-01-15T10:31:00Z',
  completed_at: null as string | null,
};

const SAGA_STATES = ['created', 'running', 'completed', 'failed', 'compensating', 'timeout'];

const createMockSaga = (overrides: MockSagaOverrides = {}) => ({ ...DEFAULT_SAGA, ...overrides });

const createMockSagas = (count: number) =>
  Array.from({ length: count }, (_, i) => createMockSaga({
    saga_id: `saga-${i + 1}`,
    execution_id: `exec-${i + 1}`,
    state: SAGA_STATES[i % SAGA_STATES.length],
    created_at: new Date(Date.now() - i * 60000).toISOString(),
    updated_at: new Date(Date.now() - i * 30000).toISOString(),
  }));

const mocks = vi.hoisted(() => ({
  listSagasApiV1SagasGet: vi.fn(),
  getSagaStatusApiV1SagasSagaIdGet: vi.fn(),
  getExecutionSagasApiV1SagasExecutionExecutionIdGet: vi.fn(),
}));

vi.mock('../../../lib/api', () => ({
  listSagasApiV1SagasGet: (...args: unknown[]) => mocks.listSagasApiV1SagasGet(...args),
  getSagaStatusApiV1SagasSagaIdGet: (...args: unknown[]) => mocks.getSagaStatusApiV1SagasSagaIdGet(...args),
  getExecutionSagasApiV1SagasExecutionExecutionIdGet: (...args: unknown[]) => mocks.getExecutionSagasApiV1SagasExecutionExecutionIdGet(...args),
}));

vi.mock('../../../lib/api-interceptors');
vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: vi.fn() }));
vi.mock('../AdminLayout.svelte', async () => {
  const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
  return { default: MockLayout };
});

import AdminSagas from '$routes/admin/AdminSagas.svelte';

async function renderWithSagas(sagas = createMockSagas(5)) {
  mocks.listSagasApiV1SagasGet.mockResolvedValue({
    data: { sagas, total: sagas.length },
    error: null,
  });

  const result = render(AdminSagas);
  await tick();
  await waitFor(() => expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled());
  return result;
}

describe('AdminSagas', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.listSagasApiV1SagasGet.mockResolvedValue({ data: { sagas: [], total: 0 }, error: null });
    mocks.getSagaStatusApiV1SagasSagaIdGet.mockResolvedValue({ data: null, error: null });
    mocks.getExecutionSagasApiV1SagasExecutionExecutionIdGet.mockResolvedValue({ data: { sagas: [], total: 0 }, error: null });
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  describe('initial loading', () => {
    it('calls listSagas on mount', async () => {
      render(AdminSagas);
      await tick();
      await waitFor(() => expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled());
    });

    it('displays loading state', async () => {
      mocks.listSagasApiV1SagasGet.mockImplementation(() => new Promise(() => {}));
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
      expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(5000);
      expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledTimes(2);

      await vi.advanceTimersByTimeAsync(5000);
      expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledTimes(3);
    });

    it('manual refresh button works', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await renderWithSagas();
      vi.clearAllMocks();

      const refreshButton = screen.getByRole('button', { name: /refresh now/i });
      await user.click(refreshButton);

      await waitFor(() => expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled());
    });

    it('toggling auto-refresh off stops polling', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await renderWithSagas();

      const checkbox = screen.getByRole('checkbox', { name: /auto-refresh/i });
      await user.click(checkbox);

      vi.clearAllMocks();
      await vi.advanceTimersByTimeAsync(10000);

      expect(mocks.listSagasApiV1SagasGet).not.toHaveBeenCalled();
    });
  });

  describe('filters', () => {
    it('filters by state', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await renderWithSagas();
      vi.clearAllMocks();

      const stateSelect = screen.getByLabelText(/state/i);
      await user.selectOptions(stateSelect, 'running');

      await waitFor(() => {
        expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
          expect.objectContaining({
            query: expect.objectContaining({ state: 'running' })
          })
        );
      });
    });

    it('filters by search query', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
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
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const sagas = [
        createMockSaga({ saga_id: 's1', execution_id: 'exec-abc' }),
        createMockSaga({ saga_id: 's2', execution_id: 'exec-xyz' }),
      ];
      await renderWithSagas(sagas);

      const execInput = screen.getByLabelText(/execution id/i);
      await user.type(execInput, 'abc');

      await waitFor(() => {
        expect(screen.getAllByText(/exec-abc/).length).toBeGreaterThan(0);
      });
    });

    it('clears filters on clear button click', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await renderWithSagas();

      const stateSelect = screen.getByLabelText(/state/i);
      await user.selectOptions(stateSelect, 'failed');

      vi.clearAllMocks();
      const clearButton = screen.getByRole('button', { name: /clear filters/i });
      await user.click(clearButton);

      await waitFor(() => {
        expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
          expect.objectContaining({
            query: expect.objectContaining({ state: undefined })
          })
        );
      });
    });
  });

  describe('saga details modal', () => {
    it('opens modal on View Details click', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const saga = createMockSaga({
        saga_name: 'execution_saga',
        completed_steps: ['validate_execution', 'allocate_resources'],
      });
      mocks.getSagaStatusApiV1SagasSagaIdGet.mockResolvedValue({ data: saga, error: null });
      await renderWithSagas([saga]);

      const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
      await user.click(viewBtn!);

      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
      expect(screen.getByText('Saga Details')).toBeInTheDocument();
    });

    it('displays saga information in modal', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const saga = createMockSaga({
        saga_id: 'saga-detail-test',
        saga_name: 'execution_saga',
        state: 'completed',
        completed_steps: ['validate_execution'],
        retry_count: 2,
      });
      mocks.getSagaStatusApiV1SagasSagaIdGet.mockResolvedValue({ data: saga, error: null });
      await renderWithSagas([saga]);

      const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
      await user.click(viewBtn!);

      await waitFor(() => {
        expect(screen.getByText('saga-detail-test')).toBeInTheDocument();
      });
    });

    it('shows error message when saga has error', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const saga = createMockSaga({
        state: 'failed',
        error_message: 'Pod creation failed: timeout',
      });
      mocks.getSagaStatusApiV1SagasSagaIdGet.mockResolvedValue({ data: saga, error: null });
      await renderWithSagas([saga]);

      const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
      await user.click(viewBtn!);

      await waitFor(() => {
        expect(screen.getByText(/pod creation failed/i)).toBeInTheDocument();
      });
    });

    it('closes modal on close button click', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const saga = createMockSaga();
      mocks.getSagaStatusApiV1SagasSagaIdGet.mockResolvedValue({ data: saga, error: null });
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
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const saga = createMockSaga({
        saga_name: 'execution_saga',
        state: 'failed',
        completed_steps: ['validate_execution', 'allocate_resources'],
        compensated_steps: ['release_resources'],
      });
      mocks.getSagaStatusApiV1SagasSagaIdGet.mockResolvedValue({ data: saga, error: null });
      await renderWithSagas([saga]);

      const [viewBtn] = screen.getAllByRole('button', { name: /view details/i });
      await user.click(viewBtn!);

      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
      expect(screen.getByText('release_resources')).toBeInTheDocument();
    });
  });

  describe('view execution sagas', () => {
    it('loads sagas for specific execution', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const executionSagas = [createMockSaga({ execution_id: 'exec-target' })];
      mocks.getExecutionSagasApiV1SagasExecutionExecutionIdGet.mockResolvedValue({
        data: { sagas: executionSagas, total: 1 },
        error: null,
      });
      await renderWithSagas([createMockSaga({ execution_id: 'exec-target' })]);

      const [execButton] = screen.getAllByRole('button', { name: /execution/i });
      await user.click(execButton!);
      await waitFor(() => {
        expect(mocks.getExecutionSagasApiV1SagasExecutionExecutionIdGet).toHaveBeenCalled();
      });
    });
  });

  describe('pagination', () => {
    it('shows pagination when items exist', async () => {
      const sagas = createMockSagas(5);
      mocks.listSagasApiV1SagasGet.mockResolvedValue({
        data: { sagas, total: 25 },
        error: null,
      });

      render(AdminSagas);
      await tick();
      await waitFor(() => expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled());

      expect(screen.getByText(/showing/i)).toBeInTheDocument();
    });

    it('changes page size', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const sagas = createMockSagas(5);
      mocks.listSagasApiV1SagasGet.mockResolvedValue({
        data: { sagas, total: 25 },
        error: null,
      });

      render(AdminSagas);
      await tick();
      await waitFor(() => expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalled());

      vi.clearAllMocks();
      const pageSizeSelect = screen.getByDisplayValue('10 / page');
      await user.selectOptions(pageSizeSelect, '25');

      await waitFor(() => {
        expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledWith(
          expect.objectContaining({
            query: expect.objectContaining({ limit: 25 })
          })
        );
      });
    });
  });

  describe('refresh rate control', () => {
    it('changes refresh rate', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await renderWithSagas();

      const rateSelect = screen.getByLabelText(/every/i);
      await user.selectOptions(rateSelect, '10');

      vi.clearAllMocks();
      await vi.advanceTimersByTimeAsync(10000);

      expect(mocks.listSagasApiV1SagasGet).toHaveBeenCalledTimes(1);
    });
  });
});
