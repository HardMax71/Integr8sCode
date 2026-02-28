import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import SagaFilters from '$components/admin/sagas/SagaFilters.svelte';

vi.mock('$lib/admin/sagas', () => ({
  SAGA_STATES: {
    created: { label: 'Created' },
    running: { label: 'Running' },
    completed: { label: 'Completed' },
    failed: { label: 'Failed' },
    compensating: { label: 'Compensating' },
    timeout: { label: 'Timeout' },
    cancelled: { label: 'Cancelled' },
  },
}));

function renderFilters(overrides: Record<string, unknown> = {}) {
  const onSearch = vi.fn();
  const onClear = vi.fn();
  const result = render(SagaFilters, {
    props: {
      searchQuery: '',
      stateFilter: '',
      executionIdFilter: '',
      onSearch,
      onClear,
      ...overrides,
    },
  });
  return { ...result, onSearch, onClear };
}

describe('SagaFilters', () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(['Search', 'State', 'Execution ID'])('renders %s filter input', (label) => {
    renderFilters();
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  });

  it('renders Clear Filters button', () => {
    renderFilters();
    expect(screen.getByText('Clear Filters')).toBeInTheDocument();
  });

  it('state filter has All States option', () => {
    renderFilters();
    const select = screen.getByLabelText('State') as HTMLSelectElement;
    expect(select.options[0]!.text).toBe('All States');
  });

  it('state filter has saga state options', () => {
    renderFilters();
    const select = screen.getByLabelText('State') as HTMLSelectElement;
    const labels = Array.from(select.options).map(o => o.text);
    expect(labels).toContain('Running');
    expect(labels).toContain('Completed');
    expect(labels).toContain('Failed');
  });

  it('calls onClear when Clear Filters is clicked', async () => {
    const { onClear } = renderFilters();
    await user.click(screen.getByText('Clear Filters'));
    expect(onClear).toHaveBeenCalledOnce();
  });

  it('search input has correct placeholder', () => {
    renderFilters();
    expect(screen.getByPlaceholderText('Search by ID, name, or error...')).toBeInTheDocument();
  });
});
