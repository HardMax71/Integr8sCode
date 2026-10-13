import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, mockApi, mockStreamEvents, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeUserResponse, fakeUserSettings } from '#lib/api/@faker-js/faker.gen.ts';
import {
    getNotificationsApiV1NotificationsGet,
    logoutApiV1AuthLogoutPost,
    notificationStreamApiV1EventsNotificationsStreamGet,
    Theme,
    updateThemeApiV1UserSettingsThemePut,
    UserRole,
} from '#lib/api/index.ts';

import * as navigation from '$app/navigation';
import { setMode, userPrefersMode } from 'mode-watcher';

import Header from '#components/Header.svelte';
import { page } from '#test/page.svelte.ts';
import { queryClient } from '#lib/query-client.ts';

/** What matchMedia answers for the desktop query, so a test can resize the window by flipping it */
class DesktopQuery extends EventTarget {
    matches = false;
}

async function openUserDropdown(): Promise<void> {
    renderWithQueryClient(Header);
    await user.click(screen.getByRole('button', { name: 'User menu' }));
}

async function openMobileMenu(): Promise<void> {
    renderWithQueryClient(Header);
    await user.click(screen.getByRole('button', { name: 'Open menu' }));
}

describe('Header', () => {
    beforeEach(() => {
        mockApi(logoutApiV1AuthLogoutPost).ok({ message: 'Logged out' });
        mockApi(updateThemeApiV1UserSettingsThemePut).ok(fakeUserSettings());
        mockApi(getNotificationsApiV1NotificationsGet).ok({ notifications: [], total: 0, unread_count: 0 });
        mockStreamEvents(notificationStreamApiV1EventsNotificationsStreamGet);
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
        it.each([
            [Theme.LIGHT, Theme.DARK],
            [Theme.DARK, Theme.SYSTEM],
            [Theme.SYSTEM, Theme.LIGHT],
        ])('goes from %s to %s without saving it when signed out', async (from, to) => {
            setMode(from);
            renderWithQueryClient(Header);
            await user.click(screen.getByTitle('Toggle theme'));
            expect(userPrefersMode.current).toBe(to);
            expect(vi.mocked(updateThemeApiV1UserSettingsThemePut)).not.toHaveBeenCalled();
        });

        it('saves the toggled theme to the user settings when signed in', async () => {
            page.data.user = fakeUserResponse();
            setMode(Theme.LIGHT);
            renderWithQueryClient(Header);
            await user.click(screen.getByTitle('Toggle theme'));
            await waitFor(() =>
                expect(vi.mocked(updateThemeApiV1UserSettingsThemePut)).toHaveBeenCalledWith(
                    expect.objectContaining({ body: { theme: Theme.DARK } }),
                ),
            );
        });
    });

    describe('unauthenticated state', () => {
        it('shows Login and Register buttons, no user dropdown', () => {
            renderWithQueryClient(Header);
            expect(screen.getByRole('link', { name: /^Login$/i })).toHaveAttribute('href', '/login');
            expect(screen.getByRole('link', { name: /^Register$/i })).toHaveAttribute('href', '/register');
            expect(screen.queryByText('Settings')).not.toBeInTheDocument();
            expect(screen.queryByRole('button', { name: 'Notifications' })).not.toBeInTheDocument();
        });
    });

    describe('authenticated state', () => {
        beforeEach(() => {
            page.data.user = {
                ...fakeUserResponse(),
                username: 'testuser',
                email: 'test@example.com',
                role: UserRole.USER,
            };
        });

        it('shows the notification center', () => {
            renderWithQueryClient(Header);
            expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument();
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
        ])('logout empties the query cache and reloads into /login when the call %s', async (_label, arrange) => {
            arrange();
            await openUserDropdown();
            queryClient.setQueryData(['left-behind'], 'previous user data');
            await user.click(await screen.findByRole('menuitem', { name: /Logout/i }));
            await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/login', { refreshAll: true }));
            expect(vi.mocked(logoutApiV1AuthLogoutPost)).toHaveBeenCalled();
            expect(queryClient.getQueryData(['left-behind'])).toBeUndefined();
        });
    });

    describe('admin user', () => {
        beforeEach(() => {
            page.data.user = { ...fakeUserResponse(), role: UserRole.ADMIN };
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
        it('shows hamburger menu and toggles on click', async () => {
            await openMobileMenu();
            await waitFor(() => {
                expect(screen.getByTestId('mobile-menu')).toBeInTheDocument();
            });
        });

        it.each([
            { label: 'signed out', role: null, expectedContent: ['Login', 'Register'] },
            {
                label: 'a user',
                role: UserRole.USER,
                expectedContent: ['mobileuser', UserRole.USER, 'Settings', 'Logout'],
            },
            { label: 'an admin', role: UserRole.ADMIN, expectedContent: ['mobileuser', UserRole.ADMIN, 'Admin Panel'] },
        ])('shows correct content for $label', async ({ role, expectedContent }) => {
            page.data.user = role ? { ...fakeUserResponse(), username: 'mobileuser', role } : null;
            await openMobileMenu();
            await waitFor(() => {
                const mobileMenu = screen.getByTestId('mobile-menu');
                expectedContent.forEach((text) => expect(mobileMenu.textContent).toContain(text));
            });
        });
    });

    describe('header structure', () => {
        it('is a banner holding the site navigation', () => {
            renderWithQueryClient(Header);
            expect(screen.getByRole('banner')).toContainElement(screen.getByRole('navigation'));
        });
    });

    describe('dropdown toggle behavior', () => {
        it('closes dropdown when clicking a menu item', async () => {
            page.data.user = fakeUserResponse();
            await openUserDropdown();
            await user.click(await screen.findByRole('menuitem', { name: /Settings/i }));
            await waitFor(() => {
                expect(screen.queryByRole('menuitem', { name: /Settings/i })).not.toBeInTheDocument();
            });
        });

        it('closes the dropdown on Escape', async () => {
            page.data.user = fakeUserResponse();
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
            const desktop = new DesktopQuery();
            vi.mocked(window.matchMedia).mockReturnValue(desktop as unknown as MediaQueryList);
            await openMobileMenu();
            await waitFor(() => {
                expect(screen.getByTestId('mobile-menu')).toBeInTheDocument();
            });

            desktop.matches = true;
            desktop.dispatchEvent(new Event('change'));

            await waitFor(() => {
                expect(screen.queryByTestId('mobile-menu')).not.toBeInTheDocument();
            });
        });
    });

    describe('mobile menu logout', () => {
        it('calls logout and navigates from mobile menu', async () => {
            page.data.user = { ...fakeUserResponse(), username: 'mobileuser' };

            await openMobileMenu();
            await waitFor(() => {
                const mobileMenu = screen.getByTestId('mobile-menu');
                expect(mobileMenu.textContent).toContain('Logout');
            });

            const logoutButton = screen.getByRole('button', { name: /Logout/i });
            await user.click(logoutButton);

            await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/login', { refreshAll: true }));
        });
    });
});
