import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user, createMockSaga, createMockSagas } from '$test/test-utils';
import SagasTable from '$components/admin/sagas/SagasTable.svelte';

vi.mock('$lib/formatters', () => ({
  formatTimestamp: vi.fn((ts: string) => `ts:${ts}`),
  formatDurationBetween: vi.fn(() => '1m 30s'),
}));

vi.mock('$lib/admin/sagas', () => ({
  getSagaStateInfo: vi.fn((state: string) => ({
    label: state.charAt(0).toUpperCase() + state.slice(1),
    color: 'badge-neutral',
    bgColor: 'bg-neutral-50',
  })),
}));

vi.mock('$components/Spinner.svelte', async () => {
  const utils = await import('$test/test-utils');
  return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderTable(props: Record<string, unknown> = {}) {
  const onViewDetails = vi.fn();
  const onViewExecution = vi.fn();
  const result = render(SagasTable, {
    props: { sagas: [], loading: false, onViewDetails, onViewExecution, ...props },
  });
  return { ...result, onViewDetails, onViewExecution };
}

describe('SagasTable', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows loading state when loading with no sagas', () => {
    renderTable({ loading: true, sagas: [] });
    expect(screen.getByText('Loading sagas...')).toBeInTheDocument();
  });

  it('shows empty state when no sagas and not loading', () => {
    renderTable({ sagas: [], loading: false });
    expect(screen.getByText('No sagas found')).toBeInTheDocument();
  });

  it.each(['Saga', 'State', 'Progress', 'Started', 'Duration'])('renders %s table header', (header) => {
    renderTable({ sagas: [createMockSaga()] });
    expect(screen.getByText(header)).toBeInTheDocument();
  });

  it('renders one row per saga in desktop table', () => {
    const sagas = createMockSagas(4);
    const { container } = renderTable({ sagas });
    const rows = container.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(4);
  });

  it('renders mobile cards for each saga', () => {
    const sagas = createMockSagas(2);
    const { container } = renderTable({ sagas });
    const mobileCards = container.querySelectorAll('.block.lg\\:hidden > div');
    expect(mobileCards).toHaveLength(2);
  });

  it('displays saga name', () => {
    renderTable({ sagas: [createMockSaga({ saga_name: 'my_saga' })] });
    const names = screen.getAllByText('my_saga');
    expect(names.length).toBeGreaterThanOrEqual(1);
  });

  it('displays truncated saga_id', () => {
    renderTable({ sagas: [createMockSaga({ saga_id: 'abcdefghijklmno' })] });
    // Desktop shows first 8 chars, mobile shows first 12 chars
    const truncated = screen.getAllByText(/ID: abcdefgh/);
    expect(truncated.length).toBeGreaterThanOrEqual(1);
  });

  it('displays state badge via getSagaStateInfo', () => {
    renderTable({ sagas: [createMockSaga({ state: 'running' })] });
    const badges = screen.getAllByText('Running');
    expect(badges.length).toBeGreaterThanOrEqual(1);
  });

  it('shows retry count when > 0', () => {
    renderTable({ sagas: [createMockSaga({ retry_count: 3 })] });
    const retries = screen.getAllByText(/3/);
    expect(retries.length).toBeGreaterThanOrEqual(1);
  });

  it('shows completed steps count', () => {
    renderTable({ sagas: [createMockSaga({ completed_steps: ['step1', 'step2'] })] });
    const stepsText = screen.getAllByText(/2 steps/);
    expect(stepsText.length).toBeGreaterThanOrEqual(1);
  });

  it('shows current step when present', () => {
    renderTable({ sagas: [createMockSaga({ current_step: 'create_pod' })] });
    const currentSteps = screen.getAllByText(/create_pod/);
    expect(currentSteps.length).toBeGreaterThanOrEqual(1);
  });

  it('calls onViewDetails when View Details clicked', async () => {
    const saga = createMockSaga({ saga_id: 'saga-click' });
    const { onViewDetails } = renderTable({ sagas: [saga] });
    const btns = screen.getAllByText('View Details');
    await user.click(btns[0]!);
    expect(onViewDetails).toHaveBeenCalledWith('saga-click');
  });

  it('calls onViewExecution when Execution button clicked in mobile view', async () => {
    const saga = createMockSaga({ execution_id: 'exec-click' });
    const { onViewExecution } = renderTable({ sagas: [saga] });
    const btns = screen.getAllByText('Execution');
    await user.click(btns[0]!);
    expect(onViewExecution).toHaveBeenCalledWith('exec-click');
  });
});
