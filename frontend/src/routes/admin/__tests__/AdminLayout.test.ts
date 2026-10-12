import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { UserRole, type UserResponse } from '#lib/api/index.ts';
import AdminLayout from '#routes/admin/+layout.svelte';

const mocks = vi.hoisted(() => ({
    page: { url: new URL('https://localhost/admin/events') },
    mockAuthStore: {
        isAuthenticated: true,
        user: null as UserResponse | null,
        csrfToken: 'token',
        verifyAuth: vi.fn(),
    },
}));

vi.mock('#stores/auth.svelte.ts', () => ({ authStore: mocks.mockAuthStore }));
vi.mock('$app/state', () => ({ page: mocks.page }));

describe('AdminLayout', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.mockAuthStore.user = { ...fakeUserResponse(), username: 'adminuser', role: UserRole.ADMIN };
    });

    function renderLayout(path = '/admin/events') {
        mocks.page.url = new URL(`https://localhost${path}`);
        const children = createRawSnippet(() => ({ render: () => '<p>page content</p>' }));
        return render(AdminLayout, { props: { children } });
    }

    it('renders the page inside the layout', async () => {
        await renderLayout();
        await waitFor(() => expect(screen.getByText('page content')).toBeInTheDocument());
    });

    it('renders sidebar with "Admin Panel" heading for admin users', async () => {
        await renderLayout();
        await waitFor(() => {
            expect(screen.getByRole('heading', { name: /admin panel/i })).toBeInTheDocument();
        });
    });

    it('renders all admin route links with correct hrefs and labels', async () => {
        await renderLayout();
        await waitFor(() => {
            expect(screen.getByText('Event Browser')).toBeInTheDocument();
        });
        expect(screen.getByText('Executions')).toBeInTheDocument();
        expect(screen.getByText('Sagas')).toBeInTheDocument();
        expect(screen.getByText('Users')).toBeInTheDocument();
        expect(screen.getByText('Settings')).toBeInTheDocument();

        const adminLinks = screen.getAllByRole('link').filter((l) => l.getAttribute('href')?.startsWith('/admin/'));
        expect(adminLinks.length).toBe(5);

        const hrefs = adminLinks.map((l) => l.getAttribute('href'));
        expect(hrefs).toContain('/admin/events');
        expect(hrefs).toContain('/admin/executions');
        expect(hrefs).toContain('/admin/sagas');
        expect(hrefs).toContain('/admin/users');
        expect(hrefs).toContain('/admin/settings');
    });

    it.each([
        ['/admin/events', 'Event Browser'],
        ['/admin/executions', 'Executions'],
        ['/admin/sagas', 'Sagas'],
        ['/admin/users', 'Users'],
        ['/admin/settings', 'Settings'],
    ])('highlights active link for path "%s"', async (path, label) => {
        await renderLayout(path);
        await waitFor(() => {
            expect(screen.getByText(label)).toBeInTheDocument();
        });
        const link = screen.getByRole('link', { name: label });
        expect(link.classList.toString()).toMatch(/bg-primary/);
        expect(link).toHaveAttribute('aria-current', 'page');
        const others = screen.getAllByRole('link').filter((l) => l !== link);
        expect(others.every((l) => !l.hasAttribute('aria-current'))).toBe(true);
    });

    it('shows user info card with exact username', async () => {
        await renderLayout();
        await waitFor(() => {
            expect(screen.getByText('Logged in as:')).toBeInTheDocument();
        });
        expect(screen.getByText('adminuser')).toBeInTheDocument();
    });
});
