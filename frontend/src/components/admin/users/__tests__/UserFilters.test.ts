import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { proxy } from 'svelte/internal/client';
import { user, selectOption } from '#test/test-utils.ts';
import UserFilters, { type UserListFilters } from '#components/admin/users/UserFilters.svelte';
import { UserRole } from '#lib/api/index.ts';

function renderFilters(overrides: Record<string, unknown> = {}) {
    const onReset = vi.fn();
    const filters = proxy<UserListFilters>({
        search: null,
        role: null,
        is_active: null,
        bypass_rate_limit: null,
        has_custom_limits: null,
        custom_multiplier: null,
    });
    const result = render(UserFilters, {
        props: {
            filters,
            showAdvancedFilters: false,
            hasFiltersActive: false,
            onReset,
            ...overrides,
        },
    });
    return { ...result, onReset, filters };
}

describe('UserFilters', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each(['Search', 'Role', 'Is Active'])('renders the %s filter', (label) => {
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
        expect(screen.getByLabelText('Has Custom Limits')).toBeInTheDocument();
        expect(screen.getByLabelText('Custom Multiplier')).toBeInTheDocument();
    });

    it('offers All and every role value as is', () => {
        renderFilters();
        const select = screen.getByLabelText('Role') as HTMLSelectElement;
        expect(Array.from(select.options).map((o) => o.text)).toEqual(['All', ...Object.values(UserRole)]);
    });

    it.each(['Is Active', 'Bypass Rate Limit', 'Has Custom Limits', 'Custom Multiplier'])(
        'offers All, Yes and No for %s',
        (label) => {
            renderFilters({ showAdvancedFilters: true });
            const select = screen.getByLabelText(label) as HTMLSelectElement;
            expect(Array.from(select.options).map((o) => o.text)).toEqual(['All', 'Yes', 'No']);
        },
    );

    it.each([
        ['Is Active', 'is_active', 'false', false],
        ['Bypass Rate Limit', 'bypass_rate_limit', 'true', true],
        ['Has Custom Limits', 'has_custom_limits', 'true', true],
        ['Custom Multiplier', 'custom_multiplier', 'false', false],
        ['Role', 'role', 'admin', 'admin'],
    ] as const)('writes the %s choice to filters.%s', (label, key, option, value) => {
        const { filters } = renderFilters({ showAdvancedFilters: true });
        selectOption(screen.getByLabelText(label), option);
        expect(filters[key]).toBe(value);
    });
});
