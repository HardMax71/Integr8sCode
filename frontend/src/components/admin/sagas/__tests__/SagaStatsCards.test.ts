import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { fakeSagaStatusResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { SagaState, type SagaStatusResponse } from '#lib/api/index.ts';
import SagaStatsCards from '#components/admin/sagas/SagaStatsCards.svelte';

const MockIcon = vi.hoisted(() => {
    const Comp = function () {
        return {};
    } as unknown as {
        new (): object;
        render: () => { html: string; css: { code: string; map: null }; head: string };
    };
    Comp.render = () => ({ html: '<svg></svg>', css: { code: '', map: null }, head: '' });
    return Comp;
});

vi.mock('#lib/admin/sagas/index.ts', () => ({
    SAGA_STATES: {
        created: { color: 'badge-neutral', bgColor: 'bg-muted', icon: MockIcon },
        running: { color: 'badge-info', bgColor: 'bg-info-soft', icon: MockIcon },
        compensating: { color: 'badge-warning', bgColor: 'bg-warning-soft', icon: MockIcon },
        completed: { color: 'badge-success', bgColor: 'bg-success-soft', icon: MockIcon },
        failed: { color: 'badge-danger', bgColor: 'bg-danger-soft', icon: MockIcon },
        timeout: { color: 'badge-warning', bgColor: 'bg-orange-soft', icon: MockIcon },
        cancelled: { color: 'badge-neutral', bgColor: 'bg-muted', icon: MockIcon },
    },
}));

function renderCards(sagas: SagaStatusResponse[] = []) {
    return render(SagaStatsCards, { props: { sagas } });
}

describe('SagaStatsCards', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each(Object.values(SagaState))('titles a card with the raw state %s', (state) => {
        renderCards();
        expect(screen.getByText(state)).toBeInTheDocument();
    });

    it('shows zero counts when no sagas', () => {
        renderCards([]);
        const zeros = screen.getAllByText('0');
        expect(zeros.length).toBe(7);
    });

    it('shows correct count for each state', () => {
        const sagas: SagaStatusResponse[] = [
            { ...fakeSagaStatusResponse(), saga_id: 's1', state: 'running' },
            { ...fakeSagaStatusResponse(), saga_id: 's2', state: 'running' },
            { ...fakeSagaStatusResponse(), saga_id: 's3', state: 'completed' },
            { ...fakeSagaStatusResponse(), saga_id: 's4', state: 'failed' },
        ];
        renderCards(sagas);
        expect(screen.getByText('2')).toBeInTheDocument();
        const ones = screen.getAllByText('1');
        expect(ones.length).toBe(2);
        const zeros = screen.getAllByText('0');
        expect(zeros.length).toBe(4);
    });

    it('updates counts when sagas change', () => {
        const { rerender } = renderCards([{ ...fakeSagaStatusResponse(), state: 'running' }]);
        expect(screen.getByText('1')).toBeInTheDocument();
        rerender({
            sagas: [
                { ...fakeSagaStatusResponse(), saga_id: 's1', state: 'completed' },
                { ...fakeSagaStatusResponse(), saga_id: 's2', state: 'completed' },
            ],
        });
        expect(screen.getByText('2')).toBeInTheDocument();
    });
});
