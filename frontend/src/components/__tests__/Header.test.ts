import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock, suppressConsoleError } from '../../__tests__/test-utils';

// vi.hoisted must contain self-contained code - cannot import external modules
const mocks = vi.hoisted(() => {
  function createMockStore<T>(initial: T) {
    let value = initial;
    const subscribers = new Set<(v: T) => void>();
    return {
      set(v: T) { value = v; subscribers.forEach(fn => fn(v)); },
      subscribe(fn: (v: T) => void) { fn(value); subscribers.add(fn); return () => subscribers.delete(fn); },
      update(fn: (v: T) => T) { this.set(fn(value)); },
    };
  }
  return {
    mockIsAuthenticated: createMockStore<boolean | null>(false),
    mockUsername: createMockStore<string | null>(null),
    mockUserRole: createMockStore<string | null>(null),
    mockUserEmail: createMockStore<string | null>(null),
    mockTheme: createMockStore<string>('auto'),
    mockLogout: vi.fn(),
    mockToggleTheme: vi.fn(),
    mockGoto: vi.fn(),
  };
});

vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: (...args: unknown[]) => mocks.mockGoto(...args) }));
vi.mock('../../stores/auth', () => ({
  get isAuthenticated() { return mocks.mockIsAuthenticated; },
  get username() { return mocks.mockUsername; },
  get userRole() { return mocks.mockUserRole; },
  get userEmail() { return mocks.mockUserEmail; },
  get logout() { return () => mocks.mockLogout(); },
}));
vi.mock('../../stores/theme', () => ({
  get theme() { return mocks.mockTheme; },
  get toggleTheme() { return () => mocks.mockToggleTheme(); },
}));
vi.mock('../NotificationCenter.svelte', () => {
  const Mock = function() { return { $$: { on_mount: [], on_destroy: [], before_update: [], after_update: [], context: new Map() } }; };
  Mock.render = () => ({ html: '<div data-testid="notification-center">NotificationCenter</div>', css: { code: '', map: null }, head: '' });
  return { default: Mock };
});

import Header from '../Header.svelte';

// Test helpers
const setAuth = (isAuth: boolean, username: string | null = null, role: string | null = null, email: string | null = null) => {
  mocks.mockIsAuthenticated.set(isAuth);
  mocks.mockUsername.set(username);
  mocks.mockUserRole.set(role);
  mocks.mockUserEmail.set(email);
};

const openUserDropdown = async (username: string) => {
  const user = userEvent.setup();
  render(Header);
  await user.click(screen.getByRole('button', { name: new RegExp(username, 'i') }));
  return user;
};

const openMobileMenu = async () => {
  const user = userEvent.setup();
  const { container } = render(Header);
  const menuButton = container.querySelector('.block.lg\\:hidden')?.querySelector('button');
  await user.click(menuButton!);
  return { user, container };
};

describe('Header', () => {
  let originalInnerWidth: number;

  beforeEach(() => {
    setupAnimationMock();
    setAuth(false);
    mocks.mockTheme.set('auto');
    mocks.mockLogout.mockReset();
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
      mocks.mockTheme.set(theme);
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
      mocks.mockUserEmail.set(null);
      await openUserDropdown('testuser');
      await waitFor(() => { expect(screen.getByText('No email set')).toBeInTheDocument(); });
    });

    it('logout calls logout and redirects', async () => {
      const user = await openUserDropdown('testuser');
      await waitFor(() => { expect(screen.getByRole('button', { name: /Logout/i })).toBeInTheDocument(); });
      await user.click(screen.getByRole('button', { name: /Logout/i }));
      expect(mocks.mockLogout).toHaveBeenCalled();
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
      const { container } = await openMobileMenu();
      await waitFor(() => { expect(container.querySelector('.lg\\:hidden.absolute')).toBeInTheDocument(); });
    });

    it.each([
      { isAuth: false, username: null, role: null, expectedContent: ['Login', 'Register'] },
      { isAuth: true, username: 'mobileuser', role: 'user', expectedContent: ['mobileuser', 'Settings', 'Logout'] },
      { isAuth: true, username: 'admin', role: 'admin', expectedContent: ['Admin Panel', 'Administrator'] },
    ])('shows correct content for auth=$isAuth role=$role', async ({ isAuth, username, role, expectedContent }) => {
      setAuth(isAuth, username, role);
      const { container } = await openMobileMenu();
      await waitFor(() => {
        const mobileMenu = container.querySelector('.lg\\:hidden.absolute');
        expectedContent.forEach(text => expect(mobileMenu?.textContent).toContain(text));
      });
    });
  });

  describe('header structure', () => {
    it('has fixed header with nav and backdrop blur', () => {
      const { container } = render(Header);
      const header = container.querySelector('header');
      expect(header).toBeInTheDocument();
      expect(header?.classList.contains('fixed')).toBe(true);
      expect(header?.classList.contains('top-0')).toBe(true);
      expect(header?.classList.contains('backdrop-blur-md')).toBe(true);
      expect(container.querySelector('nav')).toBeInTheDocument();
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

      const { container } = await openMobileMenu();
      await waitFor(() => { expect(container.querySelector('.lg\\:hidden.absolute')).toBeInTheDocument(); });

      // Resize to desktop width
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      window.dispatchEvent(new Event('resize'));

      await waitFor(() => {
        expect(container.querySelector('.lg\\:hidden.absolute')).not.toBeInTheDocument();
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

      const { user, container } = await openMobileMenu();
      await waitFor(() => {
        const mobileMenu = container.querySelector('.lg\\:hidden.absolute');
        expect(mobileMenu?.textContent).toContain('Logout');
      });

      const logoutButton = screen.getByRole('button', { name: /Logout/i });
      await user.click(logoutButton);

      expect(mocks.mockLogout).toHaveBeenCalled();
      expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
    });
  });
});
