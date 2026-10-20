import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { UserRole } from '#lib/api/index.ts';
import AdminLayout from '#routes/admin/+layout.svelte';
import { page } from '#test/page.svelte.ts';

function renderLayout(path = '/admin/events') {
    page.url = new URL(`https://localhost${path}`);
    const children = createRawSnippet(() => ({ render: () => '<p>page content</p>' }));
    const user = { ...fakeUserResponse(), username: 'adminuser', role: UserRole.ADMIN };
    return render(AdminLayout, { props: { data: { user }, params: {}, children } });
}

describe('AdminLayout', () => {
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
        expect(screen.getByText('Users')).toBeInTheDocument();
        expect(screen.getByText('Settings')).toBeInTheDocument();

        const adminLinks = screen.getAllByRole('link').filter((l) => l.getAttribute('href')?.startsWith('/admin/'));
        expect(adminLinks.length).toBe(4);

        const hrefs = adminLinks.map((l) => l.getAttribute('href'));
        expect(hrefs).toContain('/admin/events');
        expect(hrefs).toContain('/admin/executions');
        expect(hrefs).toContain('/admin/users');
        expect(hrefs).toContain('/admin/settings');
    });

    it.each([
        ['/admin/events', 'Event Browser'],
        ['/admin/executions', 'Executions'],
        ['/admin/users', 'Users'],
        ['/admin/settings', 'Settings'],
    ])('highlights active link for path "%s"', async (path, label) => {
        await renderLayout(path);
        await waitFor(() => {
            expect(screen.getByText(label)).toBeInTheDocument();
        });
        const link = screen.getByRole('link', { name: label });
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
