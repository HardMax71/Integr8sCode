import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, suppressConsoleError, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { logoutApiV1AuthLogoutPost, updateUserSettingsApiV1UserSettingsPut } from '#lib/api/index.ts';

import * as navigation from '$app/navigation';

const mocks = vi.hoisted(() => ({
    mockAuthStore: {
        isAuthenticated: false as boolean | null,
        username: null as string | null,
        userRole: null as string | null,
        userEmail: null as string | null,
        userId: null as string | null,
        csrfToken: null as string | null,
        clearAuth: vi.fn(),
        verifyAuth: vi.fn(),
    },
    mockThemeStore: {
        value: 'auto' as string,
    },
    mockToggleTheme: vi.fn(),
}));

vi.mock('#stores/auth.svelte.ts', () => ({
    get authStore() {
        return mocks.mockAuthStore;
    },
}));
vi.mock('#stores/theme.svelte.ts', () => ({
    get themeStore() {
        return mocks.mockThemeStore;
    },
    get toggleTheme() {
        return mocks.mockToggleTheme;
    },
}));
vi.mock('#components/NotificationCenter.svelte', () => {
    const M = function () {
        return {};
    } as any;
    M.render = () => ({
        html: '<div data-testid="notification-center">NotificationCenter</div>',
        css: { code: '', map: null },
        head: '',
    });
    return { default: M };
});

import Header from '#components/Header.svelte';

const setAuth = (
    isAuth: boolean,
    username: string | null = null,
    role: string | null = null,
    email: string | null = null,
) => {
    mocks.mockAuthStore.isAuthenticated = isAuth;
    mocks.mockAuthStore.username = username;
    mocks.mockAuthStore.userRole = role;
    mocks.mockAuthStore.userEmail = email;
};

describe('Header', () => {
    const openUserDropdown = async () => {
        renderWithQueryClient(Header);
        await user.click(screen.getByRole('button', { name: 'User menu' }));
    };

    const openMobileMenu = async () => {
        renderWithQueryClient(Header);
        await user.click(screen.getByRole('button', { name: 'Open menu' }));
    };

    let originalInnerWidth: number;

    beforeEach(() => {
        setAuth(false);
        mocks.mockThemeStore.value = 'auto';
        mocks.mockAuthStore.clearAuth.mockReset();
        mockApi(logoutApiV1AuthLogoutPost).ok({ message: 'Logged out' });
        mockApi(updateUserSettingsApiV1UserSettingsPut).ok({});
        mocks.mockToggleTheme.mockReset();
        vi.spyOn(navigation, 'goto');
        originalInnerWidth = window.innerWidth;
        Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
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
        Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: originalInnerWidth });
    });

    describe('branding', () => {
        it('displays logo with link to home page', () => {
            renderWithQueryClient(Header);
            const logo = screen.getByAltText('Integr8sCode Logo');
            expect(logo).toBeInTheDocument();
            expect(logo.getAttribute('src')).toBe('/favicon.png');
            expect(screen.getByText('Integr8sCode')).toBeInTheDocument();
            expect(screen.getByRole('link', { name: /Integr8sCode/i }).getAttribute('href')).toBe('/');
        });
    });

    describe('theme toggle', () => {
        it('toggles the theme without saving it when signed out', async () => {
            renderWithQueryClient(Header);
            await user.click(screen.getByTitle('Toggle theme'));
            expect(mocks.mockToggleTheme).toHaveBeenCalled();
            expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).not.toHaveBeenCalled();
        });

        it('saves the toggled theme to the user settings when signed in', async () => {
            setAuth(true, 'testuser', 'user');
            mocks.mockToggleTheme.mockImplementation(() => {
                mocks.mockThemeStore.value = 'dark';
            });
            renderWithQueryClient(Header);
            await user.click(screen.getByTitle('Toggle theme'));
            await waitFor(() =>
                expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).toHaveBeenCalledWith(
                    expect.objectContaining({ body: { theme: 'dark' } }),
                ),
            );
        });

        it.each([
            { theme: 'light', iconClass: 'lucide-sun' },
            { theme: 'dark', iconClass: 'lucide-moon' },
            { theme: 'auto', iconClass: 'lucide-monitor-cog' },
        ])('shows correct icon for $theme theme', async ({ theme, iconClass }) => {
            mocks.mockThemeStore.value = theme;
            const { container } = renderWithQueryClient(Header);
            await waitFor(() => {
                const svg = container.querySelector('[title="Toggle theme"] svg');
                expect(svg?.classList.contains(iconClass)).toBe(true);
            });
        });
    });

    describe('unauthenticated state', () => {
        it('shows Login and Register buttons, no user dropdown', () => {
            renderWithQueryClient(Header);
            expect(screen.getByRole('link', { name: /^Login$/i })).toHaveAttribute('href', '/login');
            expect(screen.getByRole('link', { name: /^Register$/i })).toHaveAttribute('href', '/register');
            expect(screen.queryByText('Settings')).not.toBeInTheDocument();
        });
    });

    describe('authenticated state', () => {
        beforeEach(() => {
            setAuth(true, 'testuser', 'user', 'test@example.com');
        });

        it('shows username and opens dropdown with user info', async () => {
            await openUserDropdown();
            await waitFor(() => {
                expect(screen.getAllByText(/testuser/i).length).toBeGreaterThan(0);
                expect(screen.getByText('test@example.com')).toBeInTheDocument();
                expect(screen.getByText('T')).toBeInTheDocument(); // initial
                expect(screen.getByRole('menuitem', { name: /Settings/i })).toHaveAttribute('href', '/settings');
                expect(screen.getByRole('menuitem', { name: /Logout/i })).toBeInTheDocument();
            });
        });

        it('shows "No email set" when email is null', async () => {
            mocks.mockAuthStore.userEmail = null;
            await openUserDropdown();
            await waitFor(() => {
                expect(screen.getByText('No email set')).toBeInTheDocument();
            });
        });

        it.each([
            ['succeeds', () => mockApi(logoutApiV1AuthLogoutPost).ok({ message: 'Logged out' })],
            ['fails', () => mockApi(logoutApiV1AuthLogoutPost).err({ detail: 'Server error' })],
        ])('logout ends the session and goes to /login when the call %s', async (_label, arrange) => {
            arrange();
            await openUserDropdown();
            await user.click(await screen.findByRole('menuitem', { name: /Logout/i }));
            await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/login'));
            expect(vi.mocked(logoutApiV1AuthLogoutPost)).toHaveBeenCalled();
            expect(mocks.mockAuthStore.clearAuth).toHaveBeenCalled();
        });
    });

    describe('admin user', () => {
        beforeEach(() => {
            setAuth(true, 'admin', 'admin', 'admin@example.com');
        });

        it('shows the Admin indicator and an Admin entry linking to the admin panel', async () => {
            await openUserDropdown();
            await waitFor(() => {
                expect(screen.getByText('(Admin)')).toBeInTheDocument();
            });
            expect(screen.getByRole('menuitem', { name: /^Admin$/ })).toHaveAttribute('href', '/admin/events');
        });
    });

    describe('mobile menu', () => {
        beforeEach(() => {
            Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });
        });

        it('shows hamburger menu and toggles on click', async () => {
            await openMobileMenu();
            await waitFor(() => {
                expect(screen.getByTestId('mobile-menu')).toBeInTheDocument();
            });
        });

        it.each([
            { isAuth: false, username: null, role: null, expectedContent: ['Login', 'Register'] },
            {
                isAuth: true,
                username: 'mobileuser',
                role: 'user',
                expectedContent: ['mobileuser', 'Settings', 'Logout'],
            },
            { isAuth: true, username: 'admin', role: 'admin', expectedContent: ['Admin Panel', 'Administrator'] },
        ])('shows correct content for auth=$isAuth role=$role', async ({ isAuth, username, role, expectedContent }) => {
            setAuth(isAuth, username, role);
            await openMobileMenu();
            await waitFor(() => {
                const mobileMenu = screen.getByTestId('mobile-menu');
                expectedContent.forEach((text) => expect(mobileMenu.textContent).toContain(text));
            });
        });
    });

    describe('header structure', () => {
        it('has fixed header with nav and backdrop blur', () => {
            renderWithQueryClient(Header);
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
            await openUserDropdown();
            await user.click(await screen.findByRole('menuitem', { name: /Settings/i }));
            await waitFor(() => {
                expect(screen.queryByRole('menuitem', { name: /Settings/i })).not.toBeInTheDocument();
            });
            restoreConsole();
        });

        it('closes the dropdown on Escape', async () => {
            setAuth(true, 'testuser', 'user');
            await openUserDropdown();
            await screen.findByRole('menuitem', { name: /Settings/i });

            await user.keyboard('{Escape}');

            await waitFor(() => {
                expect(screen.queryByRole('menuitem', { name: /Settings/i })).not.toBeInTheDocument();
            });
        });
    });

    describe('resize behavior', () => {
        it('closes mobile menu when resizing to desktop width', async () => {
            Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });

            await openMobileMenu();
            await waitFor(() => {
                expect(screen.getByTestId('mobile-menu')).toBeInTheDocument();
            });

            Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
            window.dispatchEvent(new Event('resize'));

            await waitFor(() => {
                expect(screen.queryByTestId('mobile-menu')).not.toBeInTheDocument();
            });
        });

        it('detects mobile on mount when window is narrow', () => {
            Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 500 });
            renderWithQueryClient(Header);

            expect(screen.getByTestId('mobile-menu-toggle')).toBeInTheDocument();
        });
    });

    describe('mobile menu logout', () => {
        it('calls logout and navigates from mobile menu', async () => {
            Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });
            setAuth(true, 'mobileuser', 'user');

            await openMobileMenu();
            await waitFor(() => {
                const mobileMenu = screen.getByTestId('mobile-menu');
                expect(mobileMenu.textContent).toContain('Logout');
            });

            const logoutButton = screen.getByRole('button', { name: /Logout/i });
            await user.click(logoutButton);

            await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/login'));
            expect(mocks.mockAuthStore.clearAuth).toHaveBeenCalled();
        });
    });
});
