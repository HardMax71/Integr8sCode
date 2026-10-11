import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createMockUserOverview } from '#test/test-utils.ts';

import UserOverviewModal from '#components/admin/events/UserOverviewModal.svelte';

function renderModal(
    overrides: Partial<{
        overview: ReturnType<typeof createMockUserOverview> | null;
        loading: boolean;
        open: boolean;
    }> = {},
) {
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

function detail(term: string): Element | null {
    return screen.getByText(term, { selector: 'dt' }).nextElementSibling;
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
        expect(screen.queryByText('User')).not.toBeInTheDocument();
        expect(screen.queryByText('Derived Counts')).not.toBeInTheDocument();
    });

    it('shows "No data available" when overview is null and not loading', () => {
        renderModal({ overview: null });
        expect(screen.getByText('No data available')).toBeInTheDocument();
    });

    describe('profile section', () => {
        it('heads the section with the user field', () => {
            renderModal();
            expect(screen.getByRole('heading', { name: 'User' })).toBeInTheDocument();
        });

        it.each([
            { term: 'User Id', value: 'user-1' },
            { term: 'Username', value: 'testuser' },
            { term: 'Email', value: 'test@example.com' },
            { term: 'Role', value: 'user' },
            { term: 'Is Active', value: 'Yes' },
            { term: 'Is Superuser', value: 'No' },
        ])('shows $term as $value', ({ term, value }) => {
            renderModal();
            expect(detail(term)).toHaveTextContent(value);
        });
    });

    describe('execution stats', () => {
        it('shows all stat card labels', () => {
            renderModal();
            expect(screen.getByRole('heading', { name: 'Derived Counts' })).toBeInTheDocument();
            expect(screen.getByText('Last 24 hours')).toBeInTheDocument();
            expect(screen.getByText('Succeeded')).toBeInTheDocument();
            expect(screen.getByText('80')).toBeInTheDocument();
            expect(screen.getByText('Failed')).toBeInTheDocument();
            expect(screen.getByText('10')).toBeInTheDocument();
            expect(screen.getByText('Timeout')).toBeInTheDocument();
            expect(screen.getByText('Cancelled')).toBeInTheDocument();
        });

        it('shows terminal total and total events labels', () => {
            renderModal();
            expect(detail('Terminal Total')).toHaveTextContent('100');
            expect(detail('Total Events')).toHaveTextContent('100');
        });
    });

    describe('rate limits', () => {
        it('shows rate limit section with values', () => {
            renderModal();
            expect(screen.getByRole('heading', { name: 'Rate Limit Summary' })).toBeInTheDocument();
            expect(detail('Bypass Rate Limit')).toHaveTextContent('No');
            expect(detail('Global Multiplier')).toHaveTextContent('1');
            expect(detail('Has Custom Limits')).toHaveTextContent('No');
        });

        it('hides rate limit section when rate_limit_summary is null', () => {
            const overview = createMockUserOverview();
            (overview as Record<string, unknown>).rate_limit_summary = null;
            renderModal({ overview });
            expect(screen.queryByText('Rate Limit Summary')).not.toBeInTheDocument();
        });
    });

    describe('recent events', () => {
        it('shows recent events list when present', () => {
            renderModal();
            expect(screen.getByRole('heading', { name: 'Recent Events' })).toBeInTheDocument();
        });

        it('hides recent events section when empty', () => {
            const overview = createMockUserOverview();
            overview.recent_events = [];
            renderModal({ overview });
            expect(screen.queryByText('Recent Events')).not.toBeInTheDocument();
        });
    });

    it('renders footer link to user management', () => {
        renderModal();
        const link = screen.getByRole('link', { name: 'Open User Management' });
        expect(link).toBeInTheDocument();
        expect(link).toHaveAttribute('href', '/admin/users');
    });
});
