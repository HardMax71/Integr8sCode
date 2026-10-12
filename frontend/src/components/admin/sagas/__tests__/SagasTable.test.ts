import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import { fakeSagaStatusResponse } from '#lib/api/@faker-js/faker.gen.ts';
import SagasTable from '#components/admin/sagas/SagasTable.svelte';

vi.mock('#lib/formatters.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/formatters.ts')>()),
    formatTimestamp: vi.fn((ts: string) => `ts:${ts}`),
    formatDurationBetween: vi.fn(() => '1m 30s'),
}));

vi.mock('#lib/admin/sagas/index.ts', () => ({
    getSagaStateInfo: vi.fn(() => ({ color: 'badge-neutral', bgColor: 'bg-neutral-50' })),
}));

vi.mock('#components/Spinner.svelte', async () => {
    const utils = await import('#test/test-utils.ts');
    return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderTable(props: Record<string, unknown> = {}) {
    const onViewDetails = vi.fn();
    const onViewExecution = vi.fn();
    const result = render(SagasTable, {
        props: {
            sagas: [],
            rowCount: 0,
            pagination: { pageIndex: 0, pageSize: 10 },
            loading: false,
            onViewDetails,
            onViewExecution,
            ...props,
        },
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

    it('names each column by its API key', () => {
        renderTable({ sagas: [fakeSagaStatusResponse()], rowCount: 1 });
        expect(screen.getAllByRole('columnheader').map((h) => h.textContent?.trim())).toEqual([
            'Saga Name',
            'State',
            'Progress',
            'Created At',
            'Duration',
            'Actions',
        ]);
    });

    it('renders one row per saga in desktop table', () => {
        const sagas = Array.from({ length: 4 }, () => fakeSagaStatusResponse());
        const { container } = renderTable({ sagas });
        const rows = container.querySelectorAll('tbody tr');
        expect(rows).toHaveLength(4);
    });

    it('renders a card for each saga for narrow screens', () => {
        renderTable({ sagas: Array.from({ length: 2 }, () => fakeSagaStatusResponse()), rowCount: 2 });
        expect(within(screen.getByRole('list', { name: 'Sagas' })).getAllByRole('listitem')).toHaveLength(2);
    });

    it('shows the page range and the total', () => {
        renderTable({
            sagas: Array.from({ length: 10 }, () => fakeSagaStatusResponse()),
            rowCount: 25,
            pagination: { pageIndex: 1, pageSize: 10 },
        });
        expect(screen.getByText('Showing 11 - 20 of 25 sagas')).toBeInTheDocument();
    });

    it('displays saga name', () => {
        renderTable({ sagas: [{ ...fakeSagaStatusResponse(), saga_name: 'my_saga' }] });
        const names = screen.getAllByText('my_saga');
        expect(names.length).toBeGreaterThanOrEqual(1);
    });

    it('displays truncated saga_id', () => {
        renderTable({ sagas: [{ ...fakeSagaStatusResponse(), saga_id: 'abcdefghijklmno' }] });
        const truncated = screen.getAllByText('Saga Id abcdefgh...');
        expect(truncated.length).toBeGreaterThanOrEqual(1);
    });

    it('shows the raw state in the badge', () => {
        renderTable({ sagas: [{ ...fakeSagaStatusResponse(), state: 'running' }] });
        const badges = screen.getAllByText('running');
        expect(badges.length).toBeGreaterThanOrEqual(1);
    });

    it('shows retry count when > 0', () => {
        renderTable({ sagas: [{ ...fakeSagaStatusResponse(), retry_count: 3 }] });
        const retries = screen.getAllByText('(Retry Count 3)');
        expect(retries.length).toBeGreaterThanOrEqual(1);
    });

    it('shows completed steps count', () => {
        renderTable({ sagas: [{ ...fakeSagaStatusResponse(), completed_steps: ['step1', 'step2'] }] });
        const stepsText = screen.getAllByText('Completed Steps 2');
        expect(stepsText.length).toBeGreaterThanOrEqual(1);
    });

    it('shows current step when present', () => {
        renderTable({ sagas: [{ ...fakeSagaStatusResponse(), current_step: 'create_pod' }] });
        const currentSteps = screen.getAllByText('Current Step create_pod');
        expect(currentSteps.length).toBeGreaterThanOrEqual(1);
    });

    it('calls onViewDetails when View Details clicked', async () => {
        const saga = { ...fakeSagaStatusResponse(), saga_id: 'saga-click' };
        const { onViewDetails } = renderTable({ sagas: [saga] });
        const btns = screen.getAllByText('View Details');
        await user.click(btns[0]!);
        expect(onViewDetails).toHaveBeenCalledWith('saga-click');
    });

    it('calls onViewExecution when the execution link is clicked', async () => {
        const saga = { ...fakeSagaStatusResponse(), execution_id: 'exec-click' };
        const { onViewExecution } = renderTable({ sagas: [saga] });
        await user.click(screen.getAllByRole('button', { name: 'Execution Id exec-cli...' })[0]!);
        expect(onViewExecution).toHaveBeenCalledWith('exec-click');
    });
});
