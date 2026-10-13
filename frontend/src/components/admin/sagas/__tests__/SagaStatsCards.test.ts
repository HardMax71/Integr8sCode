import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { fakeSagaStatusResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { SagaState, type SagaStatusResponse } from '#lib/api/index.ts';
import SagaStatsCards from '#components/admin/sagas/SagaStatsCards.svelte';

function renderCards(sagas: SagaStatusResponse[] = []) {
    return render(SagaStatsCards, { props: { sagas } });
}

describe('SagaStatsCards', () => {
    it.each(Object.values(SagaState))('titles a card with the raw state %s', (state) => {
        renderCards();
        expect(screen.getByText(state)).toBeInTheDocument();
    });

    it('shows zero counts when no sagas', () => {
        renderCards([]);
        const zeros = screen.getAllByText('0');
        expect(zeros.length).toBe(Object.values(SagaState).length);
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
        expect(zeros.length).toBe(Object.values(SagaState).length - 3);
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
