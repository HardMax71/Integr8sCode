import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { mockElementAnimate } from '$routes/admin/__tests__/test-utils';

const mocks = vi.hoisted(() => ({
  addToast: vi.fn(),
  mockGoto: vi.fn(),
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

vi.mock('$stores/auth.svelte', () => ({
  authStore: mocks.mockAuthStore,
}));

vi.mock('@mateothegreat/svelte5-router', () => ({
  goto: (...args: unknown[]) => mocks.mockGoto(...args),
  route: () => {},
}));

vi.mock('svelte-sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mocks.addToast('success', ...args),
    error: (...args: unknown[]) => mocks.addToast('error', ...args),
    warning: (...args: unknown[]) => mocks.addToast('warning', ...args),
    info: (...args: unknown[]) => mocks.addToast('info', ...args),
  },
}));

vi.mock('$components/Spinner.svelte', () => {
  const MockSpinner = function() {
    return { $$: { on_mount: [], on_destroy: [], before_update: [], after_update: [], context: new Map() } };
  };
  MockSpinner.render = () => ({ html: '<span data-testid="spinner">Loading</span>', css: { code: '', map: null }, head: '' });
  return { default: MockSpinner };
});

vi.mock('@lucide/svelte', () => {
  function MockIcon() {
    return { $$: { on_mount: [], on_destroy: [], before_update: [], after_update: [], context: new Map() } };
  }
  MockIcon.render = () => ({ html: '<svg></svg>', css: { code: '', map: null }, head: '' });
  return { ShieldCheck: MockIcon };
});

describe('AdminLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockElementAnimate();
    mocks.mockAuthStore.userRole = 'admin';
    mocks.mockAuthStore.username = 'adminuser';
  });

  async function renderLayout(path = '/admin/events') {
    const { default: AdminLayout } = await import('$routes/admin/AdminLayout.svelte');
    return render(AdminLayout, { props: { path } });
  }

  it('redirects non-admin users with error toast', async () => {
    mocks.mockAuthStore.userRole = 'user';
    await renderLayout();
    await waitFor(() => {
      expect(mocks.addToast).toHaveBeenCalledWith('error', 'Admin access required');
    });
    expect(mocks.mockGoto).toHaveBeenCalledWith('/');
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
    expect(screen.getByText('Sagas')).toBeInTheDocument();
    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();

    const links = screen.getAllByRole('link');
    const adminLinks = links.filter(l => l.getAttribute('href')?.startsWith('/admin/'));
    expect(adminLinks.length).toBe(4);

    const hrefs = adminLinks.map(l => l.getAttribute('href'));
    expect(hrefs).toContain('/admin/events');
    expect(hrefs).toContain('/admin/sagas');
    expect(hrefs).toContain('/admin/users');
    expect(hrefs).toContain('/admin/settings');
  });

  it.each([
    ['/admin/events', 'Event Browser'],
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
