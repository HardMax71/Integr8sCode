import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import { CircleAlert, CircleCheck, Info, TriangleAlert } from '@lucide/svelte';
import { match } from '$app/paths';
import { mockApi, renderWithQueryClient, user, type UserEventInstance } from '#test/test-utils.ts';
import { fakeNotificationResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { notificationIcon, SEVERITY_COLORS } from '#lib/notifications/display.ts';
import {
    getNotificationsApiV1NotificationsGet,
    markAllReadApiV1NotificationsMarkAllReadPost,
    markNotificationReadApiV1NotificationsNotificationIdReadPut,
    NotificationSeverity,
    type NotificationResponse,
} from '#lib/api/index.ts';

const mocks = vi.hoisted(() => ({
    mockGoto: vi.fn(),
    mockStreamConnect: vi.fn(),
    mockStreamDisconnect: vi.fn(),
}));

vi.mock('$app/navigation', () => ({ goto: mocks.mockGoto }));
vi.mock('#lib/notifications/stream.svelte.ts', () => ({
    notificationStream: {
        connect: mocks.mockStreamConnect,
        disconnect: mocks.mockStreamDisconnect,
    },
}));

const mockRequestPermission = vi.fn(async () => 'granted');
let mockNotificationPermission = 'default';

import NotificationCenter from '#components/NotificationCenter.svelte';

const createNotification = (overrides: Partial<NotificationResponse> = {}): NotificationResponse => ({
    ...fakeNotificationResponse(),
    notification_id: '1',
    subject: 'Test',
    body: 'Body',
    status: 'delivered',
    action_url: '',
    ...overrides,
});

const setNotifications = (notifications: NotificationResponse[]) => {
    mockApi(getNotificationsApiV1NotificationsGet).ok({
        notifications,
        total: notifications.length,
        unread_count: notifications.filter((n) => n.status !== 'read').length,
    });
};

const getNotifications = vi.mocked(getNotificationsApiV1NotificationsGet);
const markRead = vi.mocked(markNotificationReadApiV1NotificationsNotificationIdReadPut);
const markAllRead = vi.mocked(markAllReadApiV1NotificationsMarkAllReadPost);

/** Interacts with a notification button via click or keyboard */
const interactWithButton = async (user: UserEventInstance, button: HTMLElement, method: 'click' | 'keyboard') => {
    if (method === 'click') await user.click(button);
    else {
        button.focus();
        await user.keyboard('{Enter}');
    }
};

const iconTestCases = [
    { tags: ['completed'], icon: CircleCheck, desc: 'check' },
    { tags: ['success'], icon: CircleCheck, desc: 'check' },
    { tags: ['failed'], icon: CircleAlert, desc: 'error' },
    { tags: ['error'], icon: CircleAlert, desc: 'error' },
    { tags: ['security'], icon: CircleAlert, desc: 'error' },
    { tags: ['timeout'], icon: TriangleAlert, desc: 'warning' },
    { tags: ['warning'], icon: TriangleAlert, desc: 'warning' },
    { tags: ['unknown'], icon: Info, desc: 'info' },
    { tags: [] as string[], icon: Info, desc: 'info' },
];

const timeTestCases = [
    { offsetMs: 0, expected: 'just now' },
    { offsetMs: 5 * 60 * 1000, expected: '5m ago' },
    { offsetMs: 3 * 60 * 60 * 1000, expected: '3h ago' },
];

const badgeTestCases = [
    { count: 2, expected: '2' },
    { count: 9, expected: '9' },
    { count: 12, expected: '9+' },
];

const interactionTestCases = [
    {
        method: 'click',
        url: '/notifications',
        route: { id: '/(auth)/notifications', params: {} },
        goesTo: '/notifications',
    },
    {
        method: 'keyboard',
        url: '/notifications',
        route: { id: '/(auth)/notifications', params: {} },
        goesTo: '/notifications',
    },
    { method: 'click', url: '/api/v1/executions/e1/result', route: null, goesTo: null },
    { method: 'keyboard', url: '', route: null, goesTo: null },
] as const;

describe('NotificationCenter', () => {
    const openDropdown = async () => {
        renderWithQueryClient(NotificationCenter);
        await user.click(screen.getByRole('button', { name: /Notifications/i }));
    };

    beforeEach(() => {
        setNotifications([]);
        mockApi(markNotificationReadApiV1NotificationsNotificationIdReadPut).ok();
        mockApi(markAllReadApiV1NotificationsMarkAllReadPost).ok();
        mockNotificationPermission = 'default';
        vi.stubGlobal('Notification', {
            get permission() {
                return mockNotificationPermission;
            },
            requestPermission: mockRequestPermission,
        });
    });

    describe('bell icon and badge', () => {
        it('renders notification button with bell icon', () => {
            renderWithQueryClient(NotificationCenter);
            const button = screen.getByRole('button', { name: /Notifications/i });
            expect(button).toBeInTheDocument();
            expect(button.querySelector('svg')).toBeInTheDocument();
        });

        it('shows no badge when no unread notifications', async () => {
            setNotifications([createNotification({ subject: 'Read', status: 'read' })]);
            await openDropdown();
            await screen.findByRole('button', { name: 'View notification: Read' });
            expect(screen.getByRole('button', { name: 'Notifications' })).toHaveTextContent('');
        });

        it.each(badgeTestCases)('shows badge "$expected" for $count unread', async ({ count, expected }) => {
            setNotifications(
                Array.from({ length: count }, (_, i) => createNotification({ notification_id: String(i) })),
            );
            renderWithQueryClient(NotificationCenter);
            const bell = screen.getByRole('button', { name: 'Notifications' });
            expect(await within(bell).findByText(expected)).toBeInTheDocument();
        });
    });

    describe('dropdown behavior', () => {
        it('opens dropdown when bell clicked', async () => {
            await openDropdown();
            await waitFor(() => {
                expect(screen.getByText('Notifications')).toBeInTheDocument();
            });
        });

        it('shows empty state when no notifications', async () => {
            await openDropdown();
            await waitFor(() => {
                expect(screen.getByText('No notifications yet')).toBeInTheDocument();
            });
        });

        it('navigates to /notifications when View all clicked', async () => {
            await openDropdown();
            await user.click(await screen.findByText('View all notifications'));
            expect(mocks.mockGoto).toHaveBeenCalledWith('/notifications');
        });
    });

    describe('notification list display', () => {
        it('displays notification subjects', async () => {
            setNotifications([
                createNotification({ notification_id: '1', subject: 'Build Completed' }),
                createNotification({ notification_id: '2', subject: 'Build Failed', status: 'read' }),
            ]);
            await openDropdown();
            await waitFor(() => {
                expect(screen.getByText('Build Completed')).toBeInTheDocument();
                expect(screen.getByText('Build Failed')).toBeInTheDocument();
            });
        });
    });

    describe('mark as read functionality', () => {
        it.each([
            { status: 'delivered' as const, visible: true },
            { status: 'read' as const, visible: false },
        ])('Mark all button visible=$visible for $status', async ({ status, visible }) => {
            setNotifications([createNotification({ status })]);
            await openDropdown();
            await screen.findByRole('button', { name: 'View notification: Test' });
            expect(!!screen.queryByText('Mark all as read')).toBe(visible);
        });

        it('marks all as read, closes the dropdown and refetches', async () => {
            // Time moves only as vi.waitFor checks, so the 2s auto-read can't add a fetch on a slow machine
            vi.setTimerTickMode('manual');
            setNotifications([createNotification()]);
            await openDropdown();
            await user.click(await vi.waitFor(() => screen.getByText('Mark all as read')));
            await vi.waitFor(() => expect(screen.queryByText('Mark all as read')).not.toBeInTheDocument());
            expect(markAllRead).toHaveBeenCalled();
            expect(getNotifications).toHaveBeenCalledTimes(2);
        });

        it('skips markAsRead for already-read notifications', async () => {
            setNotifications([
                createNotification({ notification_id: 'read', subject: 'Read', status: 'read' }),
                createNotification({ notification_id: 'unread', subject: 'Unread' }),
            ]);
            await openDropdown();
            await user.click(await screen.findByRole('button', { name: 'View notification: Read' }));
            await user.click(screen.getByRole('button', { name: 'View notification: Unread' }));
            await waitFor(() =>
                expect(markRead).toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: 'unread' } })),
            );
            expect(markRead).not.toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: 'read' } }));
        });
    });

    describe('notification icons', () => {
        it.each(iconTestCases)('picks the $desc icon for tags=$tags', ({ tags, icon }) => {
            expect(notificationIcon(tags)).toBe(icon);
        });
    });

    describe('priority colors', () => {
        it.each(Object.values(NotificationSeverity))('colours the icon of a %s notification', async (severity) => {
            setNotifications([createNotification({ severity })]);
            await openDropdown();
            const item = await screen.findByRole('button', { name: 'View notification: Test' });
            expect(item.querySelector('svg')?.parentElement).toHaveClass(SEVERITY_COLORS[severity]);
        });
    });

    describe('time formatting', () => {
        it.each(timeTestCases)('shows "$expected" for $offsetMs ms ago', async ({ offsetMs, expected }) => {
            setNotifications([createNotification({ created_at: new Date(Date.now() - offsetMs).toISOString() })]);
            await openDropdown();
            await waitFor(() => {
                expect(screen.getByText(expected)).toBeInTheDocument();
            });
        });

        it('shows relative days for >24h old notifications', async () => {
            vi.setSystemTime(new Date(2026, 0, 15, 12));
            setNotifications([createNotification({ created_at: new Date(2026, 0, 13, 12).toISOString() })]);
            await openDropdown();
            await waitFor(() => {
                expect(screen.getByText('2d ago')).toBeInTheDocument();
            });
        });
    });

    describe('notification interaction', () => {
        it.each(interactionTestCases)('$method on "$url" opens $goesTo', async ({ method, url, route, goesTo }) => {
            vi.mocked(match).mockResolvedValue(route);
            setNotifications([createNotification({ subject: method, action_url: url })]);
            await openDropdown();
            const button = await screen.findByRole('button', { name: new RegExp(`View notification: ${method}`, 'i') });
            await interactWithButton(user, button, method);

            await waitFor(() =>
                expect(markRead).toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: '1' } })),
            );
            if (goesTo) await waitFor(() => expect(mocks.mockGoto).toHaveBeenCalledWith(goesTo));
            else expect(mocks.mockGoto).not.toHaveBeenCalled();
        });

        it('ignores non-Enter keydown', async () => {
            // Time moves only as vi.waitFor checks, so the 2s auto-read can't mark the first one
            vi.setTimerTickMode('manual');
            setNotifications([
                createNotification({ notification_id: 'first', subject: 'First' }),
                createNotification({ notification_id: 'second', subject: 'Second' }),
            ]);
            await openDropdown();
            (await vi.waitFor(() => screen.getByRole('button', { name: 'View notification: First' }))).focus();
            await user.keyboard('{Tab}{Enter}');
            await vi.waitFor(() =>
                expect(markRead).toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: 'second' } })),
            );
            expect(markRead).not.toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: 'first' } }));
        });
    });

    describe('outside URLs', () => {
        it.each(['click', 'keyboard'] as const)('stays in the app on %s', async (method) => {
            vi.stubGlobal('location', { href: 'https://localhost/' });
            vi.mocked(match).mockResolvedValue(null);
            setNotifications([createNotification({ subject: method, action_url: 'https://example.com/' + method })]);
            await openDropdown();
            const button = await screen.findByRole('button', { name: 'View notification: ' + method });
            await interactWithButton(user, button, method);

            await waitFor(() => expect(match).toHaveBeenCalledWith('https://example.com/' + method));
            expect(mocks.mockGoto).not.toHaveBeenCalled();
            expect(window.location.href).toBe('https://localhost/');
        });
    });

    describe('accessibility', () => {
        it('button has aria-label and items are real buttons', async () => {
            setNotifications([createNotification({ subject: 'Test' })]);
            renderWithQueryClient(NotificationCenter);
            expect(screen.getByRole('button', { name: /Notifications/i })).toHaveAttribute(
                'aria-label',
                'Notifications',
            );
            await user.click(screen.getByRole('button', { name: /Notifications/i }));
            const item = await screen.findByRole('button', { name: /View notification: Test/i });
            expect(item.tagName).toBe('BUTTON');
        });
    });

    describe('auto-mark as read', () => {
        it('marks notifications after 2s delay', async () => {
            setNotifications([
                createNotification({ notification_id: '1' }),
                createNotification({ notification_id: '2' }),
            ]);
            renderWithQueryClient(NotificationCenter);
            await user.click(screen.getByRole('button', { name: /Notifications/i }));
            await waitFor(() => expect(screen.getAllByText('Test')).toHaveLength(2));
            await vi.advanceTimersByTimeAsync(2500);
            await waitFor(() => expect(markRead).toHaveBeenCalledTimes(2));
        });
    });

    describe('stream connection', () => {
        it('loads and connects when authenticated, and refetches on every pushed notification', async () => {
            renderWithQueryClient(NotificationCenter);
            await waitFor(() => expect(getNotifications).toHaveBeenCalledTimes(1));
            expect(getNotifications).toHaveBeenCalledWith(expect.objectContaining({ query: { limit: 20 } }));
            expect(mocks.mockStreamConnect).toHaveBeenCalledTimes(1);

            const onNotification = mocks.mockStreamConnect.mock.calls[0]![0] as (n: NotificationResponse) => void;
            onNotification(createNotification({ notification_id: 'pushed' }));

            await waitFor(() => expect(getNotifications).toHaveBeenCalledTimes(2));
        });
    });

    describe('desktop notification permission', () => {
        it.each([
            { permission: 'default', shown: true },
            { permission: 'granted', shown: false },
            { permission: 'denied', shown: false },
        ])('enable button shown=$shown when permission is $permission', async ({ permission, shown }) => {
            mockNotificationPermission = permission;
            await openDropdown();
            await screen.findByText('View all notifications');
            expect(!!screen.queryByText('Enable desktop notifications')).toBe(shown);
        });

        it('calls requestPermission when enable button clicked', async () => {
            await openDropdown();
            await user.click(await screen.findByText('Enable desktop notifications'));
            expect(mockRequestPermission).toHaveBeenCalled();
        });
    });
});
