import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { match } from '$app/paths';
import { mockApi, renderWithQueryClient, user, type UserEventInstance } from '#test/test-utils.ts';
import { fakeNotificationResponse } from '#lib/api/@faker-js/faker.gen.ts';
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

const mockRequestPermission = vi.fn().mockResolvedValue('granted');
let mockNotificationPermission = 'default';
vi.stubGlobal('Notification', {
    get permission() {
        return mockNotificationPermission;
    },
    requestPermission: mockRequestPermission,
});

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

const markRead = vi.mocked(markNotificationReadApiV1NotificationsNotificationIdReadPut);

/** Mocks window.location.href for external URL testing */
const withMockedLocation = async (testFn: (mockHref: ReturnType<typeof vi.fn>) => Promise<void>) => {
    const originalLocation = window.location;
    const mockHref = vi.fn();
    Object.defineProperty(window, 'location', {
        value: { ...originalLocation, href: '' },
        writable: true,
        configurable: true,
    });
    Object.defineProperty(window.location, 'href', { set: mockHref, configurable: true });
    try {
        await testFn(mockHref);
    } finally {
        Object.defineProperty(window, 'location', { value: originalLocation, writable: true, configurable: true });
    }
};

/** Interacts with a notification button via click or keyboard */
const interactWithButton = async (user: UserEventInstance, button: HTMLElement, method: 'click' | 'keyboard') => {
    if (method === 'click') await user.click(button);
    else {
        button.focus();
        await user.keyboard('{Enter}');
    }
};

const iconTestCases = [
    { tags: ['completed'], iconClass: 'lucide-circle-check', desc: 'check' },
    { tags: ['success'], iconClass: 'lucide-circle-check', desc: 'check' },
    { tags: ['failed'], iconClass: 'lucide-circle-alert', desc: 'error' },
    { tags: ['error'], iconClass: 'lucide-circle-alert', desc: 'error' },
    { tags: ['security'], iconClass: 'lucide-circle-alert', desc: 'error' },
    { tags: ['timeout'], iconClass: 'lucide-triangle-alert', desc: 'warning' },
    { tags: ['warning'], iconClass: 'lucide-triangle-alert', desc: 'warning' },
    { tags: ['unknown'], iconClass: 'lucide-info', desc: 'info' },
    { tags: [] as string[], iconClass: 'lucide-info', desc: 'info' },
];

const SEVERITY_CSS: Record<NotificationSeverity, string> = {
    low: '.text-fg-muted',
    medium: '.text-blue-600',
    high: '.text-orange-600',
    urgent: '.text-red-600',
};
const priorityTestCases = Object.values(NotificationSeverity).map((severity) => ({
    severity,
    css: SEVERITY_CSS[severity],
}));

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

    // The popover renders in a portal on document.body, outside the component's container
    const openDropdownWithContainer = async () => {
        renderWithQueryClient(NotificationCenter);
        await user.click(screen.getByRole('button', { name: /Notifications/i }));
        return { container: document.body };
    };

    beforeEach(() => {
        setNotifications([]);
        mocks.mockGoto.mockReset();
        vi.mocked(getNotificationsApiV1NotificationsGet).mockClear();
        markRead.mockClear();
        mockApi(markNotificationReadApiV1NotificationsNotificationIdReadPut).ok();
        mockApi(markAllReadApiV1NotificationsMarkAllReadPost).ok();
        mocks.mockStreamConnect.mockReset();
        mocks.mockStreamDisconnect.mockReset();
        mockNotificationPermission = 'default';
        mockRequestPermission.mockReset().mockResolvedValue('granted');
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe('bell icon and badge', () => {
        it('renders notification button with bell icon', () => {
            renderWithQueryClient(NotificationCenter);
            const button = screen.getByRole('button', { name: /Notifications/i });
            expect(button).toBeInTheDocument();
            expect(button.querySelector('svg')).toBeInTheDocument();
        });

        it('shows no badge when no unread notifications', () => {
            const { container } = renderWithQueryClient(NotificationCenter);
            expect(container.querySelector('.bg-red-500')).not.toBeInTheDocument();
        });

        it.each(badgeTestCases)('shows badge "$expected" for $count unread', async ({ count, expected }) => {
            setNotifications(
                Array.from({ length: count }, (_, i) => createNotification({ notification_id: String(i) })),
            );
            const { container } = renderWithQueryClient(NotificationCenter);
            await waitFor(() => {
                expect(container.querySelector('.bg-red-500')?.textContent).toBe(expected);
            });
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
        it('displays notification subjects and shows unread indicator', async () => {
            setNotifications([
                createNotification({ notification_id: '1', subject: 'Build Completed' }),
                createNotification({ notification_id: '2', subject: 'Build Failed', status: 'read' }),
            ]);
            const { container } = await openDropdownWithContainer();
            await waitFor(() => {
                expect(screen.getByText('Build Completed')).toBeInTheDocument();
                expect(screen.getByText('Build Failed')).toBeInTheDocument();
                expect(container.querySelector('.bg-blue-500.rounded-full')).toBeInTheDocument();
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
            await waitFor(() => {
                expect(!!screen.queryByText('Mark all as read')).toBe(visible);
            });
        });

        it('marks all as read, closes the dropdown and refetches', async () => {
            setNotifications([createNotification()]);
            await openDropdown();
            await user.click(await screen.findByText('Mark all as read'));
            await waitFor(() => expect(screen.queryByText('Mark all as read')).not.toBeInTheDocument());
            expect(vi.mocked(markAllReadApiV1NotificationsMarkAllReadPost)).toHaveBeenCalled();
            expect(vi.mocked(getNotificationsApiV1NotificationsGet)).toHaveBeenCalledTimes(2);
        });

        it('skips markAsRead for already-read notifications', async () => {
            setNotifications([createNotification({ subject: 'Read', status: 'read' })]);
            await openDropdown();
            await user.click(await screen.findByRole('button', { name: /View notification: Read/i }));
            expect(markRead).not.toHaveBeenCalled();
        });
    });

    describe('notification icons', () => {
        it.each(iconTestCases)('shows $desc icon for tags=$tags', async ({ tags, iconClass }) => {
            const subject = tags[0] || 'NoTags';
            setNotifications([createNotification({ tags, subject })]);
            const { container } = await openDropdownWithContainer();
            await waitFor(() => {
                const svg = container.querySelector(`[aria-label*="${subject}"] svg`);
                expect(svg?.classList.contains(iconClass)).toBe(true);
            });
        });
    });

    describe('priority colors', () => {
        it.each(priorityTestCases)('applies $css for $severity', async ({ severity, css }) => {
            setNotifications([createNotification({ severity })]);
            const { container } = await openDropdownWithContainer();
            await waitFor(() => {
                expect(container.querySelector(css)).toBeInTheDocument();
            });
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
            const oldDate = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
            setNotifications([createNotification({ created_at: oldDate })]);
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
            setNotifications([createNotification({ subject: 'Test', action_url: '/test' })]);
            renderWithQueryClient(NotificationCenter);
            await user.click(screen.getByRole('button', { name: /Notifications/i }));
            screen.getByRole('button', { name: /View notification: Test/i }).focus();
            await user.keyboard('{Tab}');
            expect(markRead).not.toHaveBeenCalled();
        });
    });

    describe('outside URLs', () => {
        it.each(['click', 'keyboard'] as const)('stays in the app on %s', async (method) => {
            await withMockedLocation(async (mockHref) => {
                vi.mocked(match).mockResolvedValue(null);
                setNotifications([
                    createNotification({ subject: method, action_url: `https://example.com/${method}` }),
                ]);
                await openDropdown();
                const button = await screen.findByRole('button', {
                    name: new RegExp(`View notification: ${method}`, 'i'),
                });
                await interactWithButton(user, button, method);

                await waitFor(() => expect(match).toHaveBeenCalledWith(`https://example.com/${method}`));
                expect(mocks.mockGoto).not.toHaveBeenCalled();
                expect(mockHref).not.toHaveBeenCalled();
            });
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
            await waitFor(() => expect(vi.mocked(getNotificationsApiV1NotificationsGet)).toHaveBeenCalledTimes(1));
            expect(vi.mocked(getNotificationsApiV1NotificationsGet)).toHaveBeenCalledWith(
                expect.objectContaining({ query: { limit: 20 } }),
            );
            expect(mocks.mockStreamConnect).toHaveBeenCalledTimes(1);

            const onNotification = mocks.mockStreamConnect.mock.calls[0]![0] as (n: NotificationResponse) => void;
            onNotification(createNotification({ notification_id: 'pushed' }));

            await waitFor(() => expect(vi.mocked(getNotificationsApiV1NotificationsGet)).toHaveBeenCalledTimes(2));
        });
    });

    describe('desktop notification permission', () => {
        it('shows enable button when permission is default', async () => {
            mockNotificationPermission = 'default';
            await openDropdown();
            await waitFor(() => {
                expect(screen.getByText('Enable desktop notifications')).toBeInTheDocument();
            });
        });

        it('hides enable button when permission is granted', async () => {
            mockNotificationPermission = 'granted';
            await openDropdown();
            await waitFor(() => {
                expect(screen.queryByText('Enable desktop notifications')).not.toBeInTheDocument();
            });
        });

        it('hides enable button when permission is denied', async () => {
            mockNotificationPermission = 'denied';
            await openDropdown();
            await waitFor(() => {
                expect(screen.queryByText('Enable desktop notifications')).not.toBeInTheDocument();
            });
        });

        it('calls requestPermission when enable button clicked', async () => {
            mockNotificationPermission = 'default';
            await openDropdown();
            await user.click(await screen.findByText('Enable desktop notifications'));
            expect(mockRequestPermission).toHaveBeenCalled();
        });
    });
});
