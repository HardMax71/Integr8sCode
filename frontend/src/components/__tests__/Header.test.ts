import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, suppressConsoleError, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import {
    logoutApiV1AuthLogoutPost,
    Theme,
    updateThemeApiV1UserSettingsThemePut,
    UserRole,
    zUserSettings,
} from '#lib/api/index.ts';

import * as navigation from '$app/navigation';

const mocks = vi.hoisted(() => ({
    mockAuthStore: {
        session: { status: 'signed-out' } as Session,
        clearAuth: vi.fn(),
        verifyAuth: vi.fn(),
    },
    mockThemeStore: {
        value: 'system' as Theme,
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
import type { Session } from '#stores/auth.svelte.ts';

const ROOT = { ...fakeUserResponse(), username: 'root', role: UserRole.ADMIN, email: 'root@example.com' };

/** A matchMedia whose answer the test can flip, firing the change listeners the way a resize would */
function controllableDesktopQuery(initial: boolean): (matches: boolean) => void {
    let matches = initial;
    const listeners = new Set<EventListener>();
    vi.mocked(window.matchMedia).mockImplementation(
        (query: string) =>
            ({
                get matches() {
                    return matches;
                },
                media: query,
                onchange: null,
                addEventListener: (_type: string, listener: EventListener) => listeners.add(listener),
                removeEventListener: (_type: string, listener: EventListener) => listeners.delete(listener),
                addListener: vi.fn(),
                removeListener: vi.fn(),
                dispatchEvent: vi.fn(),
            }) as unknown as MediaQueryList,
    );
    return (next) => {
        matches = next;
        listeners.forEach((listener) => listener(new Event('change')));
    };
}

describe('Header', () => {
    const openUserDropdown = async () => {
        renderWithQueryClient(Header);
        await user.click(screen.getByRole('button', { name: 'User menu' }));
    };

    const openMobileMenu = async () => {
        renderWithQueryClient(Header);
        await user.click(screen.getByRole('button', { name: 'Open menu' }));
    };

    beforeEach(() => {
        mocks.mockAuthStore.session = { status: 'signed-out' };
        mocks.mockThemeStore.value = Theme.SYSTEM;
        mocks.mockAuthStore.clearAuth.mockReset();
        mockApi(logoutApiV1AuthLogoutPost).ok({ message: 'Logged out' });
        mockApi(updateThemeApiV1UserSettingsThemePut).ok(
            zUserSettings.parse({
                user_id: 'user-1',
                theme: Theme.DARK,
                notifications: {},
                editor: {},
                custom_settings: {},
                created_at: '2024-01-15T10:30:00Z',
                updated_at: '2024-01-15T10:30:00Z',
            }),
        );
        mocks.mockToggleTheme.mockReset();
        vi.spyOn(navigation, 'goto');
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
            expect(vi.mocked(updateThemeApiV1UserSettingsThemePut)).not.toHaveBeenCalled();
        });

        it('saves the toggled theme to the user settings when signed in', async () => {
            mocks.mockAuthStore.session = { status: 'signed-in', user: fakeUserResponse(), csrfToken: 'csrf' };
            mocks.mockToggleTheme.mockImplementation(() => {
                mocks.mockThemeStore.value = Theme.DARK;
            });
            renderWithQueryClient(Header);
            await user.click(screen.getByTitle('Toggle theme'));
            await waitFor(() =>
                expect(vi.mocked(updateThemeApiV1UserSettingsThemePut)).toHaveBeenCalledWith(
                    expect.objectContaining({ body: { theme: Theme.DARK } }),
                ),
            );
        });

        it.each([
            { theme: Theme.LIGHT, iconClass: 'lucide-sun' },
            { theme: Theme.DARK, iconClass: 'lucide-moon' },
            { theme: Theme.SYSTEM, iconClass: 'lucide-monitor-cog' },
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
            mocks.mockAuthStore.session = {
                status: 'signed-in',
                user: {
                    ...fakeUserResponse(),
                    username: 'testuser',
                    email: 'test@example.com',
                    role: UserRole.USER,
                },
                csrfToken: 'csrf',
            };
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

        it.each([
            ['succeeds', () => mockApi(logoutApiV1AuthLogoutPost).ok({ message: 'Logged out' })],
            ['fails', () => mockApi(logoutApiV1AuthLogoutPost).err({ status: 500, detail: 'Server error' })],
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
            mocks.mockAuthStore.session = { status: 'signed-in', user: ROOT, csrfToken: 'csrf' };
        });

        it('shows the admin role and an Admin entry linking to the admin panel', async () => {
            await openUserDropdown();
            await waitFor(() => {
                expect(screen.getByText(UserRole.ADMIN)).toBeInTheDocument();
            });
            expect(screen.getByRole('menuitem', { name: /^Admin$/ })).toHaveAttribute('href', '/admin/events');
        });
    });

    describe('mobile menu', () => {
        beforeEach(() => {});

        it('shows hamburger menu and toggles on click', async () => {
            await openMobileMenu();
            await waitFor(() => {
                expect(screen.getByTestId('mobile-menu')).toBeInTheDocument();
            });
        });

        it.each([
            { session: { status: 'signed-out' } as Session, expectedContent: ['Login', 'Register'] },
            {
                session: {
                    status: 'signed-in',
                    user: { ...fakeUserResponse(), username: 'mobileuser', role: UserRole.USER },
                    csrfToken: 'csrf',
                } as Session,
                expectedContent: ['mobileuser', UserRole.USER, 'Settings', 'Logout'],
            },
            {
                session: { status: 'signed-in', user: ROOT, csrfToken: 'csrf' } as Session,
                expectedContent: ['root', UserRole.ADMIN, 'Admin Panel'],
            },
        ])('shows correct content when $session.status', async ({ session, expectedContent }) => {
            mocks.mockAuthStore.session = session;
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
            mocks.mockAuthStore.session = { status: 'signed-in', user: fakeUserResponse(), csrfToken: 'csrf' };
            await openUserDropdown();
            await user.click(await screen.findByRole('menuitem', { name: /Settings/i }));
            await waitFor(() => {
                expect(screen.queryByRole('menuitem', { name: /Settings/i })).not.toBeInTheDocument();
            });
            restoreConsole();
        });

        it('closes the dropdown on Escape', async () => {
            mocks.mockAuthStore.session = { status: 'signed-in', user: fakeUserResponse(), csrfToken: 'csrf' };
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
            const resizeTo = controllableDesktopQuery(false);
            await openMobileMenu();
            await waitFor(() => {
                expect(screen.getByTestId('mobile-menu')).toBeInTheDocument();
            });

            resizeTo(true);

            await waitFor(() => {
                expect(screen.queryByTestId('mobile-menu')).not.toBeInTheDocument();
            });
        });
    });

    describe('mobile menu logout', () => {
        it('calls logout and navigates from mobile menu', async () => {
            mocks.mockAuthStore.session = {
                status: 'signed-in',
                user: { ...fakeUserResponse(), username: 'mobileuser' },
                csrfToken: 'csrf',
            };

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
