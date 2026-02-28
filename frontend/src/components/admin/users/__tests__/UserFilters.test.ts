import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { proxy } from 'svelte/internal/client';
import { user } from '$test/test-utils';
import UserFilters from '$components/admin/users/UserFilters.svelte';

function renderFilters(overrides: Record<string, unknown> = {}) {
  const onReset = vi.fn();
  const result = render(UserFilters, {
    props: {
      searchQuery: '',
      roleFilter: 'all',
      statusFilter: 'all',
      advancedFilters: proxy({ bypassRateLimit: 'all' as const, hasCustomLimits: 'all' as const, globalMultiplier: 'all' as const }),
      showAdvancedFilters: false,
      hasFiltersActive: false,
      onReset,
      ...overrides,
    },
  });
  return { ...result, onReset };
}

describe('UserFilters', () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(['Search', 'Role', 'Status'])('renders %s filter input', (label) => {
    renderFilters();
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  });

  it('renders Advanced toggle button', () => {
    renderFilters();
    expect(screen.getByText('Advanced')).toBeInTheDocument();
  });

  it('renders Reset button', () => {
    renderFilters();
    expect(screen.getByText('Reset')).toBeInTheDocument();
  });

  it.each([
    [false, 'disabled'],
    [true, 'enabled'],
  ] as const)('Reset button is %s when hasFiltersActive=%s', (active, state) => {
    renderFilters({ hasFiltersActive: active });
    const btn = screen.getByText('Reset');
    if (state === 'disabled') expect(btn).toBeDisabled();
    else expect(btn).toBeEnabled();
  });

  it('calls onReset when Reset is clicked', async () => {
    const { onReset } = renderFilters({ hasFiltersActive: true });
    await user.click(screen.getByText('Reset'));
    expect(onReset).toHaveBeenCalledOnce();
  });

  it('does not show advanced filters when showAdvancedFilters is false', () => {
    renderFilters({ showAdvancedFilters: false });
    expect(screen.queryByText('Rate Limit Filters')).not.toBeInTheDocument();
  });

  it('shows advanced filter panel when showAdvancedFilters is true', () => {
    renderFilters({ showAdvancedFilters: true });
    expect(screen.getByText('Rate Limit Filters')).toBeInTheDocument();
    expect(screen.getByLabelText('Bypass Rate Limit')).toBeInTheDocument();
    expect(screen.getByLabelText('Custom Limits')).toBeInTheDocument();
    expect(screen.getByLabelText('Global Multiplier')).toBeInTheDocument();
  });

  it.each([
    ['Role', ['all', 'user', 'moderator', 'admin']],
    ['Status', ['all', 'active', 'disabled']],
  ] as const)('%s filter has correct options', (label, expected) => {
    renderFilters();
    const select = screen.getByLabelText(label) as HTMLSelectElement;
    const options = Array.from(select.options).map(o => o.value);
    expect(options).toEqual(expected);
  });
});
