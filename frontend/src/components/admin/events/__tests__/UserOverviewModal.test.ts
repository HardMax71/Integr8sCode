import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { getUserOverviewApiV1AdminUsersUserIdOverviewGet, type AdminUserOverview } from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';
import {
    fakeAdminUserOverview,
    fakeDerivedCounts,
    fakeEventStatistics,
    fakeRateLimitSummary,
    fakeExecutionCompletedEvent,
    fakeUserResponse,
} from '#lib/api/@faker-js/faker.gen.ts';

import UserOverviewModal from '#components/admin/events/UserOverviewModal.svelte';

async function renderModal(
    overview: AdminUserOverview = {
        user: {
            ...fakeUserResponse(),
            user_id: 'user-1',
            username: 'testuser',
            email: 'test@example.com',
            role: 'user',
            is_active: true,
            is_superuser: false,
        },
        stats: { ...fakeEventStatistics(), total_events: 100 },
        derived_counts: { ...fakeDerivedCounts(), succeeded: 80, failed: 10, terminal_total: 100 },
        rate_limit_summary: {
            ...fakeRateLimitSummary(),
            bypass_rate_limit: false,
            global_multiplier: 1,
            has_custom_limits: false,
        },
        recent_events: [fakeExecutionCompletedEvent()],
    },
) {
    mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(overview);
    const onClose = vi.fn();
    const result = renderWithQueryClient(UserOverviewModal, { userId: 'user-1', onClose });
    await screen.findByRole('heading', { name: 'User' });
    return { ...result, onClose };
}

describe('UserOverviewModal', () => {
    it('loads the overview of the given user', async () => {
        await renderModal();
        expect(vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet)).toHaveBeenCalledWith(
            expect.objectContaining({ path: { user_id: 'user-1' } }),
        );
    });

    it('shows loading state and hides overview data while loading', () => {
        vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet).mockReturnValue(new Promise<never>(() => {}));
        renderWithQueryClient(UserOverviewModal, { userId: 'user-1', onClose: vi.fn() });
        expect(screen.getByText('User Overview')).toBeInTheDocument();
        expect(screen.queryByText('User')).not.toBeInTheDocument();
        expect(screen.queryByText('Derived Counts')).not.toBeInTheDocument();
    });

    it('shows "No data available" when the overview fails to load', async () => {
        mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).err({ status: 404, detail: 'Not found' });
        renderWithQueryClient(UserOverviewModal, { userId: 'user-1', onClose: vi.fn() });
        expect(await screen.findByText('No data available')).toBeInTheDocument();
    });

    describe('profile section', () => {
        it('heads the section with the user field', async () => {
            await renderModal();
            expect(screen.getByRole('heading', { name: 'User' })).toBeInTheDocument();
        });

        it('lists each field next to its value', async () => {
            await renderModal();
            expect(screen.getAllByRole('term').map((term) => term.textContent)).toEqual(
                [
                    'user_id',
                    'username',
                    'email',
                    'role',
                    'is_active',
                    'is_superuser',
                    'bypass_rate_limit',
                    'global_multiplier',
                    'has_custom_limits',
                    'terminal_total',
                    'total_events',
                ].map(fieldTitle),
            );
            expect(screen.getAllByRole('definition').map((definition) => definition.textContent)).toEqual([
                'user-1',
                'testuser',
                'test@example.com',
                'user',
                'Yes',
                'No',
                'No',
                '1',
                'No',
                '100',
                '100',
            ]);
        });
    });

    describe('execution stats', () => {
        it('shows all stat card labels', async () => {
            await renderModal();
            expect(screen.getByRole('heading', { name: 'Derived Counts' })).toBeInTheDocument();
            expect(screen.getByText('Last 24 hours')).toBeInTheDocument();
            expect(screen.getByText(fieldTitle('succeeded'))).toBeInTheDocument();
            expect(screen.getByText('80')).toBeInTheDocument();
            expect(screen.getByText(fieldTitle('failed'))).toBeInTheDocument();
            expect(screen.getByText('10')).toBeInTheDocument();
            expect(screen.getByText(fieldTitle('timeout'))).toBeInTheDocument();
            expect(screen.getByText(fieldTitle('cancelled'))).toBeInTheDocument();
        });
    });

    describe('rate limits', () => {
        it('shows rate limit section with values', async () => {
            await renderModal();
            expect(screen.getByRole('heading', { name: 'Rate Limit Summary' })).toBeInTheDocument();
        });
    });

    describe('recent events', () => {
        it('shows recent events list when present', async () => {
            await renderModal();
            expect(screen.getByRole('heading', { name: 'Recent Events' })).toBeInTheDocument();
        });

        it('hides recent events section when empty', async () => {
            await renderModal({ ...fakeAdminUserOverview(), recent_events: [] });
            expect(screen.queryByText('Recent Events')).not.toBeInTheDocument();
        });
    });

    it('renders footer link to user management', async () => {
        await renderModal();
        const link = screen.getByRole('link', { name: 'Open User Management' });
        expect(link).toBeInTheDocument();
        expect(link).toHaveAttribute('href', '/admin/users');
    });
});
