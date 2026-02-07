import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createMockStats } from '$routes/admin/__tests__/test-utils';

import EventStatsCards from '../EventStatsCards.svelte';

function renderCards(stats: ReturnType<typeof createMockStats> | null, totalEvents = 500) {
  return render(EventStatsCards, { props: { stats, totalEvents } });
}

describe('EventStatsCards', () => {
  it('renders nothing when stats is null', () => {
    const { container } = renderCards(null);
    expect(container.textContent?.trim()).toBe('');
  });

  it('shows all four stat cards when stats provided', () => {
    renderCards(createMockStats());
    expect(screen.getByText('Events (Last 24h)')).toBeInTheDocument();
    expect(screen.getByText('Error Rate (24h)')).toBeInTheDocument();
    expect(screen.getByText('Avg Execution Time (24h)')).toBeInTheDocument();
    expect(screen.getByText('Active Users (24h)')).toBeInTheDocument();
  });

  it('displays total_events with locale formatting and totalEvents denominator', () => {
    renderCards(createMockStats({ total_events: 1500 }), 10000);
    expect(screen.getByText('1,500')).toBeInTheDocument();
    expect(screen.getByText(/of 10,000 total/)).toBeInTheDocument();
  });

  it.each([
    { error_rate: 5, expectedText: '5%', expectedClass: 'text-red-600' },
    { error_rate: 0, expectedText: '0%', expectedClass: 'text-green-600' },
  ])('error rate $error_rate shows "$expectedText" with $expectedClass', ({ error_rate, expectedText, expectedClass }) => {
    const { container } = renderCards(createMockStats({ error_rate }));
    const el = screen.getByText(expectedText);
    expect(el).toBeInTheDocument();
    expect(container.querySelector(`.${expectedClass}`)).not.toBeNull();
  });

  it('formats avg_processing_time to 2 decimal places', () => {
    renderCards(createMockStats({ avg_processing_time: 3.456 }));
    expect(screen.getByText('3.46s')).toBeInTheDocument();
  });

  it('shows "0s" when avg_processing_time is falsy', () => {
    renderCards(createMockStats({ avg_processing_time: 0 }));
    expect(screen.getByText('0s')).toBeInTheDocument();
  });

  it('shows active user count from top_users array length', () => {
    renderCards(createMockStats({
      top_users: [
        { user_id: 'u1', count: 10 },
        { user_id: 'u2', count: 5 },
        { user_id: 'u3', count: 2 },
      ],
    }));
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('with events')).toBeInTheDocument();
  });
});
