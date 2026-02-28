import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user, createMockSaga } from '$test/test-utils';
import SagaDetailsModal from '$components/admin/sagas/SagaDetailsModal.svelte';

vi.mock('$lib/formatters', () => ({
  formatTimestamp: vi.fn((ts: string | null) => ts ? `ts:${ts}` : 'N/A'),
  formatDurationBetween: vi.fn(() => '1m 30s'),
}));

vi.mock('$lib/admin/sagas', () => ({
  getSagaStateInfo: vi.fn((state: string) => ({
    label: state.charAt(0).toUpperCase() + state.slice(1),
    color: 'badge-neutral',
  })),
}));

function renderModal(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onViewExecution = vi.fn();
  const result = render(SagaDetailsModal, {
    props: {
      open: true,
      saga: createMockSaga(),
      onClose,
      onViewExecution,
      ...overrides,
    },
  });
  return { ...result, onClose, onViewExecution };
}

describe('SagaDetailsModal', () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    ['open is false', { open: false }, 'Saga Details'],
    ['saga is null', { saga: null }, 'Basic Information'],
  ] as const)('does not render when %s', (_label, overrides, hiddenText) => {
    renderModal(overrides);
    expect(screen.queryByText(hiddenText)).not.toBeInTheDocument();
  });

  it.each(['Saga Details', 'Basic Information', 'Timing Information', 'Execution Steps'])(
    'shows %s section',
    (section) => {
      renderModal();
      expect(screen.getByText(section)).toBeInTheDocument();
    },
  );

  it('displays saga ID', () => {
    renderModal({ saga: createMockSaga({ saga_id: 'saga-test-123' }) });
    expect(screen.getByText('saga-test-123')).toBeInTheDocument();
  });

  it('displays saga name', () => {
    renderModal({ saga: createMockSaga({ saga_name: 'test_saga' }) });
    expect(screen.getByText('test_saga')).toBeInTheDocument();
  });

  it('displays execution ID as clickable button', () => {
    const saga = createMockSaga({ execution_id: 'exec-999' });
    renderModal({ saga });
    expect(screen.getByText('exec-999')).toBeInTheDocument();
  });

  it('displays state badge', () => {
    renderModal({ saga: createMockSaga({ state: 'completed' }) });
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  it('displays retry count', () => {
    renderModal({ saga: createMockSaga({ retry_count: 5 }) });
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('shows completed steps count', () => {
    renderModal({ saga: createMockSaga({ completed_steps: ['step1', 'step2'] }) });
    expect(screen.getByText('Completed (2)')).toBeInTheDocument();
  });

  it('lists completed steps', () => {
    renderModal({ saga: createMockSaga({ completed_steps: ['validate', 'allocate'] }) });
    expect(screen.getByText('validate')).toBeInTheDocument();
    expect(screen.getByText('allocate')).toBeInTheDocument();
  });

  it.each([
    ['completed', 'No completed steps'],
    ['compensated', 'No compensated steps'],
  ] as const)('shows "%s" empty state when no steps', (_type, emptyText) => {
    renderModal({ saga: createMockSaga({ completed_steps: [], compensated_steps: [] }) });
    expect(screen.getByText(emptyText)).toBeInTheDocument();
  });

  it('shows compensated steps count', () => {
    renderModal({ saga: createMockSaga({ compensated_steps: ['step1'] }) });
    expect(screen.getByText('Compensated (1)')).toBeInTheDocument();
  });

  it.each([
    ['current step', { current_step: 'create_pod' }, /Current Step:/, 'create_pod'],
    ['error message', { error_message: 'Pod creation failed' }, 'Error Information', 'Pod creation failed'],
  ] as const)('shows %s when present', (_label, overrides, sectionText, valueText) => {
    renderModal({ saga: createMockSaga(overrides) });
    expect(screen.getByText(sectionText)).toBeInTheDocument();
    expect(screen.getByText(valueText)).toBeInTheDocument();
  });

  it.each([
    ['current step', { current_step: null }, /Current Step:/],
    ['error section', { error_message: null }, 'Error Information'],
  ] as const)('hides %s when null', (_label, overrides, hiddenText) => {
    renderModal({ saga: createMockSaga(overrides) });
    expect(screen.queryByText(hiddenText)).not.toBeInTheDocument();
  });

  it('calls onViewExecution when execution ID button clicked', async () => {
    const saga = createMockSaga({ execution_id: 'exec-click' });
    const { onViewExecution, onClose } = renderModal({ saga });
    await user.click(screen.getByText('exec-click'));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onViewExecution).toHaveBeenCalledWith('exec-click');
  });
});
