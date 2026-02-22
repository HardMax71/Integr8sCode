import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createMockUserOverview } from '$test/test-utils';

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('X'));
vi.mock('$components/Spinner.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<div>Loading...</div>', 'spinner'));
vi.mock('$components/EventTypeIcon.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<span>icon</span>'));

import UserOverviewModal from '../UserOverviewModal.svelte';

function renderModal(overrides: Partial<{
  overview: ReturnType<typeof createMockUserOverview> | null;
  loading: boolean;
  open: boolean;
}> = {}) {
  const onClose = vi.fn();
  const overview = ('overview' in overrides ? overrides.overview : createMockUserOverview()) ?? null;
  const result = render(UserOverviewModal, {
    props: {
      overview,
      loading: overrides.loading ?? false,
      open: overrides.open ?? true,
      onClose,
    },
  });
  return { ...result, onClose };
}

describe('UserOverviewModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    renderModal({ open: false });
    expect(screen.queryByText('User Overview')).not.toBeInTheDocument();
  });

  it('shows loading state and hides overview data when loading', () => {
    renderModal({ loading: true, overview: null });
    expect(screen.queryByText('Profile')).not.toBeInTheDocument();
    expect(screen.queryByText('Execution Stats (last 24h)')).not.toBeInTheDocument();
  });

  it('shows "No data available" when overview is null and not loading', () => {
    renderModal({ overview: null });
    expect(screen.getByText('No data available')).toBeInTheDocument();
  });

  describe('profile section', () => {
    it.each([
      { label: 'User ID:', value: 'user-1' },
      { label: 'Username:', value: 'testuser' },
      { label: 'Email:', value: 'test@example.com' },
      { label: 'Role:', value: 'user' },
    ])('shows $label $value', ({ label, value }) => {
      renderModal();
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByText(value)).toBeInTheDocument();
    });

    it('shows Active: Yes and Superuser: No', () => {
      renderModal();
      expect(screen.getByText('Active:')).toBeInTheDocument();
      expect(screen.getByText('Superuser:')).toBeInTheDocument();
      // 'No' appears for Superuser, Bypass, and Custom Rules — use getAllByText
      const noElements = screen.getAllByText('No');
      expect(noElements.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('execution stats', () => {
    it('shows all stat card labels', () => {
      renderModal();
      expect(screen.getByText('Execution Stats (last 24h)')).toBeInTheDocument();
      expect(screen.getByText('Succeeded')).toBeInTheDocument();
      expect(screen.getByText('80')).toBeInTheDocument();
      expect(screen.getByText('Failed')).toBeInTheDocument();
      expect(screen.getByText('10')).toBeInTheDocument();
      expect(screen.getByText('Timeout')).toBeInTheDocument();
      expect(screen.getByText('Cancelled')).toBeInTheDocument();
    });

    it('shows terminal total and total events labels', () => {
      renderModal();
      expect(screen.getByText(/Terminal Total:/)).toBeInTheDocument();
      expect(screen.getByText(/Total Events:/)).toBeInTheDocument();
      // Both terminal_total and stats.total_events are 100 — verify at least one renders
      const hundreds = screen.getAllByText('100');
      expect(hundreds).toHaveLength(2);
    });
  });

  describe('rate limits', () => {
    it('shows rate limit section with values', () => {
      renderModal();
      expect(screen.getByText('Rate Limits')).toBeInTheDocument();
      expect(screen.getByText('Bypass:')).toBeInTheDocument();
      expect(screen.getByText('Global Multiplier:')).toBeInTheDocument();
      expect(screen.getByText('Custom Rules:')).toBeInTheDocument();
    });

    it('hides rate limit section when rate_limit_summary is null', () => {
      const overview = createMockUserOverview();
      (overview as Record<string, unknown>).rate_limit_summary = null;
      renderModal({ overview });
      expect(screen.queryByText('Rate Limits')).not.toBeInTheDocument();
    });
  });

  describe('recent events', () => {
    it('shows recent events list when present', () => {
      renderModal();
      expect(screen.getByText('Recent Execution Events')).toBeInTheDocument();
    });

    it('hides recent events section when empty', () => {
      const overview = createMockUserOverview();
      overview.recent_events = [];
      renderModal({ overview });
      expect(screen.queryByText('Recent Execution Events')).not.toBeInTheDocument();
    });
  });

  it('renders footer link to user management', () => {
    renderModal();
    const link = screen.getByRole('link', { name: 'Open User Management' });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/admin/users');
  });
});
