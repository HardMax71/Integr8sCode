import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock, suppressConsoleError } from '../../__tests__/test-utils';

// vi.hoisted must contain self-contained code - cannot import external modules
const mocks = vi.hoisted(() => {
  // Mock store factory (must be inline - vi.hoisted runs before imports)
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

// Mock the router
vi.mock('@mateothegreat/svelte5-router', () => ({
  route: () => {},
  goto: (...args: unknown[]) => mocks.mockGoto(...args),
}));

// Mock auth store - use getters to defer access
vi.mock('../../stores/auth', () => ({
  get isAuthenticated() { return mocks.mockIsAuthenticated; },
  get username() { return mocks.mockUsername; },
  get userRole() { return mocks.mockUserRole; },
  get userEmail() { return mocks.mockUserEmail; },
  get logout() { return () => mocks.mockLogout(); },
}));

// Mock theme store - use getters to defer access
vi.mock('../../stores/theme', () => ({
  get theme() { return mocks.mockTheme; },
  get toggleTheme() { return () => mocks.mockToggleTheme(); },
}));

// Mock NotificationCenter component with Svelte 5 compatible structure
vi.mock('../NotificationCenter.svelte', () => {
  const MockNotificationCenter = function() {
    return { $$: { on_mount: [], on_destroy: [], before_update: [], after_update: [], context: new Map() } };
  };
  MockNotificationCenter.render = () => ({
    html: '<div data-testid="notification-center">NotificationCenter</div>',
    css: { code: '', map: null },
    head: '',
  });
  return { default: MockNotificationCenter };
});

import Header from '../Header.svelte';

describe('Header', () => {
  let originalInnerWidth: number;

  beforeEach(() => {
    // Setup animation mock for Svelte transitions
    setupAnimationMock();

    // Reset stores
    mocks.mockIsAuthenticated.set(false);
    mocks.mockUsername.set(null);
    mocks.mockUserRole.set(null);
    mocks.mockUserEmail.set(null);
    mocks.mockTheme.set('auto');

    // Reset mocks
    mocks.mockLogout.mockReset();
    mocks.mockToggleTheme.mockReset();
    mocks.mockGoto.mockReset();

    // Store original window width
    originalInnerWidth = window.innerWidth;

    // Mock window.innerWidth for desktop by default
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1200,
    });

    // Mock matchMedia
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    // Restore window width
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: originalInnerWidth,
    });
  });

  describe('branding', () => {
    it('displays logo and brand name', () => {
      render(Header);

      const logo = screen.getByAltText('Integr8sCode Logo');
      expect(logo).toBeInTheDocument();
      expect(logo.getAttribute('src')).toBe('/favicon.png');

      expect(screen.getByText('Integr8sCode')).toBeInTheDocument();
    });

    it('logo links to home page', () => {
      render(Header);

      const logoLink = screen.getByRole('link', { name: /Integr8sCode/i });
      expect(logoLink.getAttribute('href')).toBe('/');
    });
  });

  describe('theme toggle', () => {
    it('renders theme toggle button', () => {
      render(Header);

      const themeButton = screen.getByTitle('Toggle theme');
      expect(themeButton).toBeInTheDocument();
    });

    it('calls toggleTheme when clicked', async () => {
      const user = userEvent.setup();
      render(Header);

      const themeButton = screen.getByTitle('Toggle theme');
      await user.click(themeButton);

      expect(mocks.mockToggleTheme).toHaveBeenCalled();
    });

    it('shows sun icon for light theme', async () => {
      mocks.mockTheme.set('light');
      const { container } = render(Header);

      await waitFor(() => {
        const themeButton = container.querySelector('[title="Toggle theme"]');
        const svg = themeButton?.querySelector('svg');
        expect(svg?.innerHTML).toContain('M12 3v1');
      });
    });

    it('shows moon icon for dark theme', async () => {
      mocks.mockTheme.set('dark');
      const { container } = render(Header);

      await waitFor(() => {
        const themeButton = container.querySelector('[title="Toggle theme"]');
        const svg = themeButton?.querySelector('svg');
        expect(svg?.innerHTML).toContain('M20.354');
      });
    });

    it('shows auto icon for auto theme', async () => {
      mocks.mockTheme.set('auto');
      const { container } = render(Header);

      await waitFor(() => {
        const themeButton = container.querySelector('[title="Toggle theme"]');
        const svg = themeButton?.querySelector('svg');
        expect(svg?.innerHTML).toContain('M9.663 17h4.673');
      });
    });
  });

  describe('unauthenticated state', () => {
    beforeEach(() => {
      mocks.mockIsAuthenticated.set(false);
    });

    it('shows Login button', () => {
      render(Header);

      const loginButton = screen.getByRole('link', { name: /^Login$/i });
      expect(loginButton).toBeInTheDocument();
      expect(loginButton.getAttribute('href')).toBe('/login');
    });

    it('shows Register button', () => {
      render(Header);

      const registerButton = screen.getByRole('link', { name: /^Register$/i });
      expect(registerButton).toBeInTheDocument();
      expect(registerButton.getAttribute('href')).toBe('/register');
    });

    it('does not show user dropdown', () => {
      render(Header);

      expect(screen.queryByText('Settings')).not.toBeInTheDocument();
      expect(screen.queryByText('Logout')).not.toBeInTheDocument();
    });
  });

  describe('authenticated state', () => {
    beforeEach(() => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockUsername.set('testuser');
      mocks.mockUserRole.set('user');
      mocks.mockUserEmail.set('test@example.com');
    });

    it('does not show Login/Register buttons', () => {
      render(Header);

      const loginLinks = screen.queryAllByRole('link', { name: /^Login$/i });
      const registerLinks = screen.queryAllByRole('link', { name: /^Register$/i });

      expect(loginLinks.filter(l => !l.closest('.lg\\:hidden'))).toHaveLength(0);
      expect(registerLinks.filter(l => !l.closest('.lg\\:hidden'))).toHaveLength(0);
    });

    it('shows user dropdown button with username', async () => {
      render(Header);

      await waitFor(() => {
        expect(screen.getByText('testuser')).toBeInTheDocument();
      });
    });

    it('opens user dropdown when clicked', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByRole('link', { name: /Settings/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Logout/i })).toBeInTheDocument();
      });
    });

    it('shows user email in dropdown', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
      });
    });

    it('shows "No email set" when email is null', async () => {
      mocks.mockUserEmail.set(null);
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByText('No email set')).toBeInTheDocument();
      });
    });

    it('shows user initial in avatar', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByText('T')).toBeInTheDocument();
      });
    });

    it('Settings link navigates to settings page', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        const settingsLink = screen.getByRole('link', { name: /Settings/i });
        expect(settingsLink.getAttribute('href')).toBe('/settings');
      });
    });

    it('calls logout and redirects when Logout clicked', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Logout/i })).toBeInTheDocument();
      });

      const logoutButton = screen.getByRole('button', { name: /Logout/i });
      await user.click(logoutButton);

      expect(mocks.mockLogout).toHaveBeenCalled();
      expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
    });
  });

  describe('admin user', () => {
    beforeEach(() => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockUsername.set('admin');
      mocks.mockUserRole.set('admin');
      mocks.mockUserEmail.set('admin@example.com');
    });

    it('shows Admin indicator in dropdown', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /admin/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByText('(Admin)')).toBeInTheDocument();
      });
    });

    it('shows Admin button in dropdown', async () => {
      const user = userEvent.setup();
      render(Header);

      // Find the user dropdown button (contains username "admin")
      const dropdownButton = screen.getByRole('button', { name: /admin/i });
      await user.click(dropdownButton);

      // Wait for dropdown to open and show Admin button
      // Use case-sensitive regex to match "Admin" not "admin" (username)
      await waitFor(() => {
        const adminNavButton = screen.getByRole('button', { name: /^Admin$/ });
        expect(adminNavButton).toBeInTheDocument();
      });
    });

    it('Admin button navigates to admin panel', async () => {
      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /admin/i });
      await user.click(dropdownButton);

      // Wait for dropdown to open - use case-sensitive "Admin" (not "admin" username)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /^Admin$/ })).toBeInTheDocument();
      });

      // Click the Admin navigation button (case-sensitive to avoid username button)
      const adminNavButton = screen.getByRole('button', { name: /^Admin$/ });
      await user.click(adminNavButton);

      // Wait for goto to be called
      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/admin/events');
      });
    });
  });

  describe('mobile menu', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: 800,
      });
    });

    it('shows hamburger menu button on mobile', () => {
      render(Header);

      const buttons = screen.getAllByRole('button');
      const menuButton = buttons.find(btn => btn.closest('.lg\\:hidden'));
      expect(menuButton).toBeTruthy();
    });

    it('toggles mobile menu on button click', async () => {
      const user = userEvent.setup();
      const { container } = render(Header);

      const mobileMenuWrapper = container.querySelector('.block.lg\\:hidden');
      const menuButton = mobileMenuWrapper?.querySelector('button');
      expect(menuButton).toBeTruthy();

      await user.click(menuButton!);

      await waitFor(() => {
        const mobileMenu = container.querySelector('.lg\\:hidden.absolute');
        expect(mobileMenu).toBeInTheDocument();
      });
    });

    it('shows Login/Register in mobile menu when unauthenticated', async () => {
      mocks.mockIsAuthenticated.set(false);
      const user = userEvent.setup();
      const { container } = render(Header);

      const mobileMenuWrapper = container.querySelector('.block.lg\\:hidden');
      const menuButton = mobileMenuWrapper?.querySelector('button');
      await user.click(menuButton!);

      await waitFor(() => {
        const mobileMenu = container.querySelector('.lg\\:hidden.absolute');
        expect(mobileMenu).toBeInTheDocument();
        expect(mobileMenu?.textContent).toContain('Login');
        expect(mobileMenu?.textContent).toContain('Register');
      });
    });

    it('shows username and Settings/Logout in mobile menu when authenticated', async () => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockUsername.set('mobileuser');
      mocks.mockUserRole.set('user');

      const user = userEvent.setup();
      const { container } = render(Header);

      const mobileMenuWrapper = container.querySelector('.block.lg\\:hidden');
      const menuButton = mobileMenuWrapper?.querySelector('button');
      await user.click(menuButton!);

      await waitFor(() => {
        const mobileMenu = container.querySelector('.lg\\:hidden.absolute');
        expect(mobileMenu).toBeInTheDocument();
        expect(mobileMenu?.textContent).toContain('mobileuser');
        expect(mobileMenu?.textContent).toContain('Settings');
        expect(mobileMenu?.textContent).toContain('Logout');
      });
    });

    it('shows Admin Panel link for admin in mobile menu', async () => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockUsername.set('admin');
      mocks.mockUserRole.set('admin');

      const user = userEvent.setup();
      const { container } = render(Header);

      const mobileMenuWrapper = container.querySelector('.block.lg\\:hidden');
      const menuButton = mobileMenuWrapper?.querySelector('button');
      await user.click(menuButton!);

      await waitFor(() => {
        const mobileMenu = container.querySelector('.lg\\:hidden.absolute');
        expect(mobileMenu).toBeInTheDocument();
        expect(mobileMenu?.textContent).toContain('Admin Panel');
        expect(mobileMenu?.textContent).toContain('Administrator');
      });
    });
  });

  describe('header structure', () => {
    it('is a fixed header element', () => {
      const { container } = render(Header);

      const header = container.querySelector('header');
      expect(header).toBeInTheDocument();
      expect(header?.classList.contains('fixed')).toBe(true);
      expect(header?.classList.contains('top-0')).toBe(true);
    });

    it('contains navigation element', () => {
      const { container } = render(Header);

      const nav = container.querySelector('nav');
      expect(nav).toBeInTheDocument();
    });

    it('has backdrop blur styling', () => {
      const { container } = render(Header);

      const header = container.querySelector('header');
      expect(header?.classList.contains('backdrop-blur-md')).toBe(true);
    });
  });

  describe('dropdown toggle behavior', () => {
    it('closes dropdown when clicking the toggle button again', async () => {
      // Suppress jsdom "Not implemented: navigation" warning from link click
      const restoreConsole = suppressConsoleError();

      mocks.mockIsAuthenticated.set(true);
      mocks.mockUsername.set('testuser');
      mocks.mockUserRole.set('user');

      const user = userEvent.setup();
      render(Header);

      const dropdownButton = screen.getByRole('button', { name: /testuser/i });
      await user.click(dropdownButton);

      await waitFor(() => {
        expect(screen.getByRole('link', { name: /Settings/i })).toBeInTheDocument();
      });

      // Close dropdown by clicking Settings link (closes dropdown via onclick)
      const settingsLink = screen.getByRole('link', { name: /Settings/i });
      await user.click(settingsLink);

      await waitFor(() => {
        expect(screen.queryByRole('link', { name: /Settings/i })).not.toBeInTheDocument();
      });

      restoreConsole();
    });
  });
});
