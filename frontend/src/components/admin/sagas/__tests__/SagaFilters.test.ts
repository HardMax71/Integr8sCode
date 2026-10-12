import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import { SagaState } from '#lib/api/index.ts';
import SagaFilters from '#components/admin/sagas/SagaFilters.svelte';

function renderFilters() {
    const onClear = vi.fn();
    const result = render(SagaFilters, {
        props: { filters: { search: null, state: null, execution_id: null }, onClear },
    });
    return { ...result, onClear };
}

describe('SagaFilters', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each(['Search', 'State', 'Execution Id'])('renders %s filter input', (label) => {
        renderFilters();
        expect(screen.getByLabelText(label)).toBeInTheDocument();
    });

    it('renders Clear Filters button', () => {
        renderFilters();
        expect(screen.getByText('Clear Filters')).toBeInTheDocument();
    });

    it('state filter offers All, then every saga state as the API names it', () => {
        renderFilters();
        const select = screen.getByLabelText('State') as HTMLSelectElement;
        expect(Array.from(select.options).map((o) => o.text)).toEqual(['All', ...Object.values(SagaState)]);
        expect(Array.from(select.options).map((o) => o.value)).toEqual(['', ...Object.values(SagaState)]);
    });

    it('calls onClear when Clear Filters is clicked', async () => {
        const { onClear } = renderFilters();
        await user.click(screen.getByText('Clear Filters'));
        expect(onClear).toHaveBeenCalledOnce();
    });
});
