import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { suppressConsoleError } from '$test/test-utils';

const mocks = vi.hoisted(() => ({
  mockAuthStore: {
    isAuthenticated: false as boolean | null,
    username: null as string | null,
    userRole: null as string | null,
    userEmail: null as string | null,
    userId: null as string | null,
    csrfToken: null as string | null,
    logout: vi.fn(),
    login: vi.fn(),
    verifyAuth: vi.fn(),
    fetchUserProfile: vi.fn(),
  },
  mockThemeStore: {
    value: 'auto' as string,
  },
  mockToggleTheme: vi.fn(),
  mockGoto: vi.fn(),
}));

vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: mocks.mockGoto }));
vi.mock('../../stores/auth.svelte', () => ({
  get authStore() { return mocks.mockAuthStore; },
}));
vi.mock('../../stores/theme.svelte', () => ({
  get themeStore() { return mocks.mockThemeStore; },
  get toggleTheme() { return mocks.mockToggleTheme; },
}));
vi.mock('../NotificationCenter.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent(
    '<div>NotificationCenter</div>', 'notification-center'));

import Header from '$components/Header.svelte';

// Test helpers
const setAuth = (isAuth: boolean, username: string | null = null, role: string | null = null, email: string | null = null) => {
  mocks.mockAuthStore.isAuthenticated = isAuth;
  mocks.mockAuthStore.username = username;
  mocks.mockAuthStore.userRole = role;
  mocks.mockAuthStore.userEmail = email;
};

const openUserDropdown = async (_username: string) => {
  const user = userEvent.setup();
  render(Header);
  await user.click(screen.getByRole('button', { name: 'User menu' }));
  return user;
};

const openMobileMenu = async () => {
  const user = userEvent.setup();
  render(Header);
  await user.click(screen.getByRole('button', { name: 'Open menu' }));
  return { user };
};

describe('Header', () => {
  let originalInnerWidth: number;

  beforeEach(() => {
    setAuth(false);
    mocks.mockThemeStore.value = 'auto';
    mocks.mockAuthStore.logout.mockReset();
    mocks.mockToggleTheme.mockReset();
    mocks.mockGoto.mockReset();
    originalInnerWidth = window.innerWidth;
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: originalInnerWidth });
  });

  describe('branding', () => {
    it('displays logo with link to home page', () => {
      render(Header);
      const logo = screen.getByAltText('Integr8sCode Logo');
      expect(logo).toBeInTheDocument();
      expect(logo.getAttribute('src')).toBe('/favicon.png');
      expect(screen.getByText('Integr8sCode')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Integr8sCode/i }).getAttribute('href')).toBe('/');
    });
  });

  describe('theme toggle', () => {
    it('renders and calls toggleTheme when clicked', async () => {
      const user = userEvent.setup();
      render(Header);
      const themeButton = screen.getByTitle('Toggle theme');
      expect(themeButton).toBeInTheDocument();
      await user.click(themeButton);
      expect(mocks.mockToggleTheme).toHaveBeenCalled();
    });

    it.each([
      { theme: 'light', iconClass: 'lucide-sun' },
      { theme: 'dark', iconClass: 'lucide-moon' },
      { theme: 'auto', iconClass: 'lucide-monitor-cog' },
    ])('shows correct icon for $theme theme', async ({ theme, iconClass }) => {
      mocks.mockThemeStore.value = theme;
      const { container } = render(Header);
      await waitFor(() => {
        const svg = container.querySelector('[title="Toggle theme"] svg');
        expect(svg?.classList.contains(iconClass)).toBe(true);
      });
    });
  });

  describe('unauthenticated state', () => {
    it('shows Login and Register buttons, no user dropdown', () => {
      render(Header);
      expect(screen.getByRole('link', { name: /^Login$/i })).toHaveAttribute('href', '/login');
      expect(screen.getByRole('link', { name: /^Register$/i })).toHaveAttribute('href', '/register');
      expect(screen.queryByText('Settings')).not.toBeInTheDocument();
    });
  });

  describe('authenticated state', () => {
    beforeEach(() => { setAuth(true, 'testuser', 'user', 'test@example.com'); });

    it('shows username and opens dropdown with user info', async () => {
      await openUserDropdown('testuser');
      await waitFor(() => {
        expect(screen.getAllByText(/testuser/i).length).toBeGreaterThan(0);
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
        expect(screen.getByText('T')).toBeInTheDocument(); // initial
        expect(screen.getByRole('link', { name: /Settings/i })).toHaveAttribute('href', '/settings');
        expect(screen.getByRole('button', { name: /Logout/i })).toBeInTheDocument();
      });
    });

    it('shows "No email set" when email is null', async () => {
      mocks.mockAuthStore.userEmail = null;
      await openUserDropdown('testuser');
      await waitFor(() => { expect(screen.getByText('No email set')).toBeInTheDocument(); });
    });

    it('logout calls logout and redirects', async () => {
      const user = await openUserDropdown('testuser');
      await waitFor(() => { expect(screen.getByRole('button', { name: /Logout/i })).toBeInTheDocument(); });
      await user.click(screen.getByRole('button', { name: /Logout/i }));
      expect(mocks.mockAuthStore.logout).toHaveBeenCalled();
      expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
    });
  });

  describe('admin user', () => {
    beforeEach(() => { setAuth(true, 'admin', 'admin', 'admin@example.com'); });

    it('shows Admin indicator and button in dropdown', async () => {
      await openUserDropdown('admin');
      await waitFor(() => {
        expect(screen.getByText('(Admin)')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /^Admin$/ })).toBeInTheDocument();
      });
    });

    it('Admin button navigates to admin panel', async () => {
      const user = await openUserDropdown('admin');
      await waitFor(() => { expect(screen.getByRole('button', { name: /^Admin$/ })).toBeInTheDocument(); });
      await user.click(screen.getByRole('button', { name: /^Admin$/ }));
      await waitFor(() => { expect(mocks.mockGoto).toHaveBeenCalledWith('/admin/events'); });
    });
  });

  describe('mobile menu', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });
    });

    it('shows hamburger menu and toggles on click', async () => {
      await openMobileMenu();
      await waitFor(() => { expect(document.body.querySelector('.lg\\:hidden.absolute')).toBeInTheDocument(); });
    });

    it.each([
      { isAuth: false, username: null, role: null, expectedContent: ['Login', 'Register'] },
      { isAuth: true, username: 'mobileuser', role: 'user', expectedContent: ['mobileuser', 'Settings', 'Logout'] },
      { isAuth: true, username: 'admin', role: 'admin', expectedContent: ['Admin Panel', 'Administrator'] },
    ])('shows correct content for auth=$isAuth role=$role', async ({ isAuth, username, role, expectedContent }) => {
      setAuth(isAuth, username, role);
      await openMobileMenu();
      await waitFor(() => {
        const mobileMenu = document.body.querySelector('.lg\\:hidden.absolute');
        expectedContent.forEach(text => expect(mobileMenu?.textContent).toContain(text));
      });
    });
  });

  describe('header structure', () => {
    it('has fixed header with nav and backdrop blur', () => {
      render(Header);
      const header = screen.getByRole('banner');
      expect(header).toBeInTheDocument();
      expect(header).toHaveClass('fixed');
      expect(header).toHaveClass('top-0');
      expect(header).toHaveClass('backdrop-blur-md');
      expect(screen.getByRole('navigation')).toBeInTheDocument();
    });
  });

  describe('dropdown toggle behavior', () => {
    it('closes dropdown when clicking a menu item', async () => {
      const restoreConsole = suppressConsoleError();
      setAuth(true, 'testuser', 'user');
      const user = await openUserDropdown('testuser');
      await waitFor(() => { expect(screen.getByRole('link', { name: /Settings/i })).toBeInTheDocument(); });
      await user.click(screen.getByRole('link', { name: /Settings/i }));
      await waitFor(() => { expect(screen.queryByRole('link', { name: /Settings/i })).not.toBeInTheDocument(); });
      restoreConsole();
    });

    it('closes dropdown when clicking outside', async () => {
      setAuth(true, 'testuser', 'user');
      await openUserDropdown('testuser');
      await waitFor(() => { expect(screen.getByRole('link', { name: /Settings/i })).toBeInTheDocument(); });

      // Click outside the dropdown
      document.body.click();

      await waitFor(() => {
        expect(screen.queryByRole('link', { name: /Settings/i })).not.toBeInTheDocument();
      });
    });
  });

  describe('resize behavior', () => {
    it('closes mobile menu when resizing to desktop width', async () => {
      // Start in mobile mode
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });

      await openMobileMenu();
      await waitFor(() => { expect(document.body.querySelector('.lg\\:hidden.absolute')).toBeInTheDocument(); });

      // Resize to desktop width
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      window.dispatchEvent(new Event('resize'));

      await waitFor(() => {
        expect(document.body.querySelector('.lg\\:hidden.absolute')).not.toBeInTheDocument();
      });
    });

    it('detects mobile on mount when window is narrow', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 500 });
      const { container } = render(Header);

      // Mobile menu toggle should be visible
      expect(container.querySelector('.block.lg\\:hidden')).toBeInTheDocument();
    });
  });

  describe('mobile menu logout', () => {
    it('calls logout and navigates from mobile menu', async () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });
      setAuth(true, 'mobileuser', 'user');

      const { user } = await openMobileMenu();
      await waitFor(() => {
        const mobileMenu = document.body.querySelector('.lg\\:hidden.absolute');
        expect(mobileMenu?.textContent).toContain('Logout');
      });

      const logoutButton = screen.getByRole('button', { name: /Logout/i });
      await user.click(logoutButton);

      expect(mocks.mockAuthStore.logout).toHaveBeenCalled();
      expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
    });
  });
});
