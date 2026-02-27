import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { toast } from 'svelte-sonner';
import * as router from '@mateothegreat/svelte5-router';
import AdminLayout from '$routes/admin/AdminLayout.svelte';

const mocks = vi.hoisted(() => ({
  mockAuthStore: {
    isAuthenticated: true,
    username: 'adminuser',
    userRole: 'admin',
    userId: 'user-1',
    userEmail: 'admin@test.com',
    csrfToken: 'token',
    verifyAuth: vi.fn(),
  },
}));

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));

vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: vi.fn() }));

describe('AdminLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(toast, 'success');
    vi.spyOn(toast, 'error');
    vi.spyOn(toast, 'warning');
    vi.spyOn(toast, 'info');
    mocks.mockAuthStore.userRole = 'admin';
    mocks.mockAuthStore.username = 'adminuser';
  });

  function renderLayout(path = '/admin/events') {
    return render(AdminLayout, { props: { path } });
  }

  it('redirects non-admin users with error toast', async () => {
    mocks.mockAuthStore.userRole = 'user';
    await renderLayout();
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('Admin access required');
    });
    expect(router.goto).toHaveBeenCalledWith('/');
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

    const adminLinks = screen.getAllByRole('link').filter(l => l.getAttribute('href')?.startsWith('/admin/'));
    expect(adminLinks.length).toBe(5);

    const hrefs = adminLinks.map(l => l.getAttribute('href'));
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
  });

  it('shows user info card with exact username', async () => {
    await renderLayout();
    await waitFor(() => {
      expect(screen.getByText('Logged in as:')).toBeInTheDocument();
    });
    expect(screen.getByText('adminuser')).toBeInTheDocument();
  });
});
