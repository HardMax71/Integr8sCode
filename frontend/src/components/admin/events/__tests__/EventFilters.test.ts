import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import { EVENT_TYPES } from '#lib/admin/events/eventTypes.ts';
import type { EventFilter } from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';

import EventFilters from '#components/admin/events/EventFilters.svelte';

function renderFilters(overrides: Partial<{ onApply: () => void; onClear: () => void; filters: EventFilter }> = {}) {
    const onApply = overrides.onApply ?? vi.fn();
    const onClear = overrides.onClear ?? vi.fn();
    const filters: EventFilter = overrides.filters ?? {};
    const result = render(EventFilters, { props: { filters, onApply, onClear } });
    return { ...result, onApply, onClear };
}

describe('EventFilters', () => {
    it('renders heading and both action buttons', () => {
        renderFilters();
        expect(screen.getByText('Filter Events')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Clear All' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument();
    });

    it.each([
        { id: 'event-types-filter', key: 'event_types' },
        { id: 'search-filter', key: 'search_text' },
        { id: 'aggregate-filter', key: 'aggregate_id' },
        { id: 'user-filter', key: 'user_id' },
        { id: 'service-filter', key: 'service_name' },
        { id: 'start-time-filter', key: 'start_time' },
        { id: 'end-time-filter', key: 'end_time' },
    ])('renders the $key filter with id=$id', ({ id, key }) => {
        renderFilters();
        expect(screen.getByLabelText(fieldTitle(key))).toBeInTheDocument();
        expect(document.getElementById(id)).not.toBeNull();
    });

    it('event types select lists all EVENT_TYPES as options', () => {
        renderFilters();
        const select = screen.getByLabelText(fieldTitle('event_types')) as HTMLSelectElement;
        const options = Array.from(select.options).map((o) => o.value);
        expect(options).toEqual(EVENT_TYPES);
    });

    it('calls onApply when Apply button is clicked', async () => {
        const { onApply } = renderFilters();
        await user.click(screen.getByRole('button', { name: 'Apply' }));
        expect(onApply).toHaveBeenCalledOnce();
    });

    it('calls onClear when Clear All button is clicked', async () => {
        const { onClear } = renderFilters();
        await user.click(screen.getByRole('button', { name: 'Clear All' }));
        expect(onClear).toHaveBeenCalledOnce();
    });

    it('text inputs accept user input', async () => {
        renderFilters();
        const searchInput = screen.getByLabelText('Search Text') as HTMLInputElement;
        await user.type(searchInput, 'test query');
        expect(searchInput.value).toBe('test query');
    });
});
