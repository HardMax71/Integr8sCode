import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { getUserOverviewApiV1AdminUsersUserIdOverviewGet, type AdminUserOverview } from '#lib/api/index.ts';
import {
    fakeAdminUserOverview,
    fakeEventStatistics,
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
        derived_counts: { succeeded: 80, failed: 10, timeout: 5, cancelled: 5, terminal_total: 100 },
        rate_limit_summary: { bypass_rate_limit: false, global_multiplier: 1, has_custom_limits: false },
        recent_events: [fakeExecutionCompletedEvent()],
    },
) {
    mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(overview);
    const onClose = vi.fn();
    const result = renderWithQueryClient(UserOverviewModal, { userId: 'user-1', onClose });
    await screen.findByRole('heading', { name: 'User' });
    return { ...result, onClose };
}

function detail(term: string): Element | null {
    return screen.getByText(term, { selector: 'dt' }).nextElementSibling;
}

describe('UserOverviewModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

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

        it.each([
            { term: 'User Id', value: 'user-1' },
            { term: 'Username', value: 'testuser' },
            { term: 'Email', value: 'test@example.com' },
            { term: 'Role', value: 'user' },
            { term: 'Is Active', value: 'Yes' },
            { term: 'Is Superuser', value: 'No' },
        ])('shows $term as $value', async ({ term, value }) => {
            await renderModal();
            expect(detail(term)).toHaveTextContent(value);
        });
    });

    describe('execution stats', () => {
        it('shows all stat card labels', async () => {
            await renderModal();
            expect(screen.getByRole('heading', { name: 'Derived Counts' })).toBeInTheDocument();
            expect(screen.getByText('Last 24 hours')).toBeInTheDocument();
            expect(screen.getByText('Succeeded')).toBeInTheDocument();
            expect(screen.getByText('80')).toBeInTheDocument();
            expect(screen.getByText('Failed')).toBeInTheDocument();
            expect(screen.getByText('10')).toBeInTheDocument();
            expect(screen.getByText('Timeout')).toBeInTheDocument();
            expect(screen.getByText('Cancelled')).toBeInTheDocument();
        });

        it('shows terminal total and total events labels', async () => {
            await renderModal();
            expect(detail('Terminal Total')).toHaveTextContent('100');
            expect(detail('Total Events')).toHaveTextContent('100');
        });
    });

    describe('rate limits', () => {
        it('shows rate limit section with values', async () => {
            await renderModal();
            expect(screen.getByRole('heading', { name: 'Rate Limit Summary' })).toBeInTheDocument();
            expect(detail('Bypass Rate Limit')).toHaveTextContent('No');
            expect(detail('Global Multiplier')).toHaveTextContent('1');
            expect(detail('Has Custom Limits')).toHaveTextContent('No');
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
