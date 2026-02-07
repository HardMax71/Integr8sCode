import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { EVENT_TYPES, createDefaultEventFilters } from '$lib/admin/events/eventTypes';

import EventFilters from '../EventFilters.svelte';

function renderFilters(overrides: Partial<{ onApply: () => void; onClear: () => void }> = {}) {
  const onApply = overrides.onApply ?? vi.fn();
  const onClear = overrides.onClear ?? vi.fn();
  const filters = createDefaultEventFilters();
  const result = render(EventFilters, { props: { filters, onApply, onClear } });
  return { ...result, onApply, onClear };
}

describe('EventFilters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders heading and both action buttons', () => {
    renderFilters();
    expect(screen.getByText('Filter Events')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear All' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument();
  });

  it.each([
    { id: 'event-types-filter', label: 'Event Types' },
    { id: 'search-filter', label: 'Search' },
    { id: 'correlation-filter', label: 'Correlation ID' },
    { id: 'aggregate-filter', label: 'Aggregate ID' },
    { id: 'user-filter', label: 'User ID' },
    { id: 'service-filter', label: 'Service' },
    { id: 'start-time-filter', label: 'Start Time' },
    { id: 'end-time-filter', label: 'End Time' },
  ])('renders "$label" filter with id=$id', ({ id, label }) => {
    renderFilters();
    expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(document.getElementById(id)).not.toBeNull();
  });

  it('event types select lists all EVENT_TYPES as options', () => {
    renderFilters();
    const select = screen.getByLabelText('Event Types') as HTMLSelectElement;
    const options = Array.from(select.options).map(o => o.value);
    expect(options).toEqual(EVENT_TYPES);
  });

  it('calls onApply when Apply button is clicked', async () => {
    const user = userEvent.setup();
    const { onApply } = renderFilters();
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledOnce();
  });

  it('calls onClear when Clear All button is clicked', async () => {
    const user = userEvent.setup();
    const { onClear } = renderFilters();
    await user.click(screen.getByRole('button', { name: 'Clear All' }));
    expect(onClear).toHaveBeenCalledOnce();
  });

  it('text inputs accept user input', async () => {
    const user = userEvent.setup();
    renderFilters();
    const searchInput = screen.getByLabelText('Search') as HTMLInputElement;
    await user.type(searchInput, 'test query');
    expect(searchInput.value).toBe('test query');
  });
});
