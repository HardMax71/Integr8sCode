import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import type { EventStatsResponse } from '#lib/api/index.ts';
import { fakeEventStatsResponse } from '#lib/api/@faker-js/faker.gen.ts';

import EventStatsCards from '#components/admin/events/EventStatsCards.svelte';

function renderCards(stats: EventStatsResponse | null, totalEvents = 500) {
    return render(EventStatsCards, { props: { stats, totalEvents } });
}

describe('EventStatsCards', () => {
    it('renders nothing when stats is null', () => {
        const { container } = renderCards(null);
        expect(container.textContent?.trim()).toBe('');
    });

    it('shows all four stat cards when stats provided', () => {
        renderCards(fakeEventStatsResponse());
        expect(screen.getByText('Last 24 hours')).toBeInTheDocument();
        expect(screen.getByText('Total Events')).toBeInTheDocument();
        expect(screen.getByText('Error Rate')).toBeInTheDocument();
        expect(screen.getByText('Avg Processing Time')).toBeInTheDocument();
        expect(screen.getByText('Top Users')).toBeInTheDocument();
    });

    it('displays total_events with locale formatting and totalEvents denominator', () => {
        renderCards({ ...fakeEventStatsResponse(), total_events: 1500 }, 10000);
        expect(screen.getByText((1500).toLocaleString())).toBeInTheDocument();
        expect(screen.getByText(new RegExp(`of ${(10000).toLocaleString()} total`))).toBeInTheDocument();
    });

    it.each([
        { error_rate: 5, expectedText: '5%', expectedClass: 'text-red-600' },
        { error_rate: 0, expectedText: '0%', expectedClass: 'text-green-600' },
    ])(
        'error rate $error_rate shows "$expectedText" with $expectedClass',
        ({ error_rate, expectedText, expectedClass }) => {
            const { container } = renderCards({ ...fakeEventStatsResponse(), error_rate });
            const el = screen.getByText(expectedText);
            expect(el).toBeInTheDocument();
            expect(container.querySelector(`.${expectedClass}`)).not.toBeNull();
        },
    );

    it('formats avg_processing_time to 2 decimal places', () => {
        renderCards({ ...fakeEventStatsResponse(), avg_processing_time: 3.456 });
        expect(screen.getByText('3.46s')).toBeInTheDocument();
    });

    it('formats a zero avg_processing_time like any other', () => {
        renderCards({ ...fakeEventStatsResponse(), avg_processing_time: 0 });
        expect(screen.getByText('0.00s')).toBeInTheDocument();
    });

    it('shows active user count from top_users array length', () => {
        renderCards({
            ...fakeEventStatsResponse(),
            top_users: [
                { user_id: 'u1', event_count: 10 },
                { user_id: 'u2', event_count: 5 },
                { user_id: 'u3', event_count: 2 },
            ],
        });
        expect(screen.getByText('3')).toBeInTheDocument();
    });
});
