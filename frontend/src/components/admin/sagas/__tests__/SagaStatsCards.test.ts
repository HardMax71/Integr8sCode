import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createMockSaga } from '$test/test-utils';
import type { SagaStatusResponse } from '$lib/api';
import SagaStatsCards from '$components/admin/sagas/SagaStatsCards.svelte';

const MockIcon = vi.hoisted(() => {
  const Comp = function () { return {}; } as unknown as {
    new (): object;
    render: () => { html: string; css: { code: string; map: null }; head: string };
  };
  Comp.render = () => ({ html: '<svg></svg>', css: { code: '', map: null }, head: '' });
  return Comp;
});

vi.mock('$lib/admin/sagas', () => ({
  SAGA_STATES: {
    created: { label: 'Created', color: 'badge-neutral', bgColor: 'bg-neutral-50', icon: MockIcon },
    running: { label: 'Running', color: 'badge-info', bgColor: 'bg-blue-50', icon: MockIcon },
    compensating: { label: 'Compensating', color: 'badge-warning', bgColor: 'bg-yellow-50', icon: MockIcon },
    completed: { label: 'Completed', color: 'badge-success', bgColor: 'bg-green-50', icon: MockIcon },
    failed: { label: 'Failed', color: 'badge-danger', bgColor: 'bg-red-50', icon: MockIcon },
    timeout: { label: 'Timeout', color: 'badge-warning', bgColor: 'bg-orange-50', icon: MockIcon },
    cancelled: { label: 'Cancelled', color: 'badge-neutral', bgColor: 'bg-neutral-50', icon: MockIcon },
  },
}));

function renderCards(sagas: SagaStatusResponse[] = []) {
  return render(SagaStatsCards, { props: { sagas } });
}

describe('SagaStatsCards', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders a card for each saga state', () => {
    renderCards();
    expect(screen.getByText('Created')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Compensating')).toBeInTheDocument();
    expect(screen.getByText('Timeout')).toBeInTheDocument();
    expect(screen.getByText('Cancelled')).toBeInTheDocument();
  });

  it('shows zero counts when no sagas', () => {
    renderCards([]);
    const zeros = screen.getAllByText('0');
    expect(zeros.length).toBe(7);
  });

  it('shows correct count for each state', () => {
    const sagas = [
      createMockSaga({ saga_id: 's1', state: 'running' }),
      createMockSaga({ saga_id: 's2', state: 'running' }),
      createMockSaga({ saga_id: 's3', state: 'completed' }),
      createMockSaga({ saga_id: 's4', state: 'failed' }),
    ];
    renderCards(sagas);
    expect(screen.getByText('2')).toBeInTheDocument();
    const ones = screen.getAllByText('1');
    expect(ones.length).toBe(2);
    const zeros = screen.getAllByText('0');
    expect(zeros.length).toBe(4);
  });

  it('updates counts when sagas change', () => {
    const { rerender } = renderCards([createMockSaga({ state: 'running' })]);
    expect(screen.getByText('1')).toBeInTheDocument();
    rerender({
      sagas: [
        createMockSaga({ saga_id: 's1', state: 'completed' }),
        createMockSaga({ saga_id: 's2', state: 'completed' }),
      ],
    });
    expect(screen.getByText('2')).toBeInTheDocument();
  });
});
