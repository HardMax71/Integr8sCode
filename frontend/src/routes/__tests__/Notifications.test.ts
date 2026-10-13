import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { fakeNotificationResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { toast } from 'svelte-sonner';
import { queryClient } from '#lib/query-client.ts';
import {
    deleteNotificationApiV1NotificationsNotificationIdDelete,
    getNotificationsApiV1NotificationsGet,
    markAllReadApiV1NotificationsMarkAllReadPost,
    markNotificationReadApiV1NotificationsNotificationIdReadPut,
    type NotificationResponse,
} from '#lib/api/index.ts';
import Notifications from '#routes/(auth)/notifications/+page.svelte';

const getNotifications = vi.mocked(getNotificationsApiV1NotificationsGet);
const markRead = vi.mocked(markNotificationReadApiV1NotificationsNotificationIdReadPut);
const markAllRead = vi.mocked(markAllReadApiV1NotificationsMarkAllReadPost);
const deleteNotification = vi.mocked(deleteNotificationApiV1NotificationsNotificationIdDelete);

function setNotifications(notifications: NotificationResponse[], unreadCount = 0) {
    mockApi(getNotificationsApiV1NotificationsGet).ok({
        notifications,
        total: notifications.length,
        unread_count: unreadCount,
    });
}

describe('Notifications', () => {
    beforeEach(() => {
        setNotifications([]);
        mockApi(markNotificationReadApiV1NotificationsNotificationIdReadPut).ok();
        mockApi(markAllReadApiV1NotificationsMarkAllReadPost).ok();
        mockApi(deleteNotificationApiV1NotificationsNotificationIdDelete).ok({ message: 'Notification deleted' });
    });

    function renderNotifications() {
        return renderWithQueryClient(Notifications);
    }

    it('loads the latest 100 notifications on mount', async () => {
        renderNotifications();
        await waitFor(() => {
            expect(getNotifications).toHaveBeenCalledWith(expect.objectContaining({ query: { limit: 100 } }));
        });
    });

    it('shows empty state when no notifications', async () => {
        renderNotifications();
        await waitFor(() => {
            expect(screen.getByText('No notifications yet')).toBeInTheDocument();
        });
        expect(screen.getByText(/you'll see notifications here/i)).toBeInTheDocument();
    });

    describe('Notification rendering', () => {
        it('renders notification subject, body, channel, severity, and tags', async () => {
            setNotifications(
                [
                    {
                        ...fakeNotificationResponse(),
                        subject: 'Execution Complete',
                        body: 'Your script finished running',
                        channel: 'webhook',
                        severity: 'high',
                        tags: ['completed', 'exec:abc123'],
                        status: 'delivered',
                    },
                ],
                1,
            );

            renderNotifications();
            await waitFor(() => {
                expect(screen.getByText('Execution Complete')).toBeInTheDocument();
            });
            expect(screen.getByText('Your script finished running')).toBeInTheDocument();
            expect(screen.getByText('webhook')).toBeInTheDocument();
            expect(screen.getByText('high')).toBeInTheDocument();
            expect(screen.getByText('completed')).toBeInTheDocument();
        });

        it('shows the read status as is', async () => {
            setNotifications([{ ...fakeNotificationResponse(), status: 'read' }]);

            renderNotifications();
            await waitFor(() => {
                expect(screen.getByText('read')).toBeInTheDocument();
            });
        });

        it('shows up to 6 tag chips', async () => {
            const tags = ['tag1', 'tag2', 'tag3', 'tag4', 'tag5', 'tag6', 'tag7', 'tag8'];
            setNotifications([{ ...fakeNotificationResponse(), tags }]);

            renderNotifications();
            await waitFor(() => {
                expect(screen.getByText('tag1')).toBeInTheDocument();
            });
            expect(screen.getByText('tag6')).toBeInTheDocument();
            expect(screen.queryByText('tag7')).not.toBeInTheDocument();
        });
    });

    describe('Timestamp formatting', () => {
        it.each([
            [0, 'just now'],
            [3 * 60 * 1000, '3m ago'],
            [5 * 60 * 60 * 1000, '5h ago'],
            [2 * 24 * 60 * 60 * 1000, '2d ago'],
        ])('formats %dms ago as "%s"', async (msAgo, expected) => {
            vi.setSystemTime(new Date(2026, 0, 15, 12));
            setNotifications([
                { ...fakeNotificationResponse(), created_at: new Date(Date.now() - msAgo).toISOString() },
            ]);

            renderNotifications();
            await waitFor(() => {
                expect(screen.getByText(expected)).toBeInTheDocument();
            });
        });
    });

    describe('Mark as read', () => {
        it('marks the clicked unread notification as read and refetches', async () => {
            setNotifications([{ ...fakeNotificationResponse(), notification_id: 'n-42', status: 'delivered' }], 1);

            renderNotifications();
            await user.click(await screen.findByTitle('Mark as read'));
            await waitFor(() => expect(getNotifications).toHaveBeenCalledTimes(2));
            expect(markRead).toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: 'n-42' } }));
        });

        it('offers no mark-as-read button for a read notification', async () => {
            setNotifications([
                {
                    ...fakeNotificationResponse(),
                    notification_id: 'n-read',
                    subject: 'Test Notification',
                    status: 'read',
                },
            ]);

            renderNotifications();
            await screen.findByText('Test Notification');
            expect(screen.queryByTitle('Mark as read')).not.toBeInTheDocument();
            await user.click(screen.getByText('Test Notification'));
            expect(markRead).not.toHaveBeenCalled();
        });

        it('marks a notification as read from the keyboard', async () => {
            setNotifications([{ ...fakeNotificationResponse(), notification_id: 'n-key', status: 'delivered' }], 1);

            renderNotifications();
            (await screen.findByTitle('Mark as read')).focus();
            await user.keyboard('{Enter}');
            await waitFor(() =>
                expect(markRead).toHaveBeenCalledWith(expect.objectContaining({ path: { notification_id: 'n-key' } })),
            );
        });
    });

    describe('Mark all as read', () => {
        it('button only visible when unreadCount > 0 and notifications exist', async () => {
            renderNotifications();
            await screen.findByText('No notifications yet');
            expect(screen.queryByRole('button', { name: /mark all as read/i })).not.toBeInTheDocument();
        });

        it('marks all as read and shows success toast', async () => {
            setNotifications(
                Array.from({ length: 3 }, (_, i) => ({ ...fakeNotificationResponse(), notification_id: `n-${i}` })),
                2,
            );

            renderNotifications();
            await user.click(await screen.findByRole('button', { name: /mark all as read/i }));
            await waitFor(() => {
                expect(toast.success).toHaveBeenCalledWith('All notifications marked as read');
            });
            expect(markAllRead).toHaveBeenCalled();
        });

        it('shows no success toast when the call fails', async () => {
            mockApi(markAllReadApiV1NotificationsMarkAllReadPost).err({ status: 500, detail: 'boom' });
            setNotifications(
                Array.from({ length: 2 }, (_, i) => ({ ...fakeNotificationResponse(), notification_id: `n-${i}` })),
                1,
            );

            renderNotifications();
            await user.click(await screen.findByRole('button', { name: /mark all as read/i }));
            await waitFor(() => expect(queryClient.getMutationCache().getAll()[0]?.state.status).toBe('error'));
            expect(markAllRead).toHaveBeenCalled();
            expect(toast.success).not.toHaveBeenCalled();
        });
    });

    describe('Delete', () => {
        it('deletes by id, shows success toast and refetches', async () => {
            setNotifications([{ ...fakeNotificationResponse(), notification_id: 'del-1' }]);

            renderNotifications();
            await user.click(await screen.findByRole('button', { name: 'Delete notification' }));
            await waitFor(() => {
                expect(toast.success).toHaveBeenCalledWith('Notification deleted');
            });
            expect(deleteNotification).toHaveBeenCalledWith(
                expect.objectContaining({ path: { notification_id: 'del-1' } }),
            );
            expect(getNotifications).toHaveBeenCalledTimes(2);
        });

        it('shows no success toast when the delete fails', async () => {
            mockApi(deleteNotificationApiV1NotificationsNotificationIdDelete).err({ status: 500, detail: 'boom' });
            setNotifications([{ ...fakeNotificationResponse(), notification_id: 'del-fail' }]);

            renderNotifications();
            await user.click(await screen.findByRole('button', { name: 'Delete notification' }));
            await waitFor(() => expect(queryClient.getMutationCache().getAll()[0]?.state.status).toBe('error'));
            expect(deleteNotification).toHaveBeenCalled();
            expect(toast.success).not.toHaveBeenCalled();
        });

        it('prevents double-click deletion', async () => {
            mockApi(deleteNotificationApiV1NotificationsNotificationIdDelete).mock.mockImplementation(
                () => new Promise(() => {}),
            );
            setNotifications([{ ...fakeNotificationResponse(), notification_id: 'dbl-1' }]);

            renderNotifications();
            const deleteBtn = await screen.findByRole('button', { name: 'Delete notification' });
            await user.click(deleteBtn);
            await waitFor(() => expect(deleteBtn).toBeDisabled());
            await user.click(deleteBtn);
            expect(deleteNotification).toHaveBeenCalledTimes(1);
        });
    });

    describe('Filter', () => {
        it('applies tag filters on button click', async () => {
            renderNotifications();
            await screen.findByText('No notifications yet');

            await user.type(screen.getByLabelText('Include Tags'), 'exec,completed');
            await user.type(screen.getByLabelText('Exclude Tags'), 'alert');
            await user.type(screen.getByLabelText('Tag Prefix'), 'exec:');
            expect(getNotifications).toHaveBeenCalledTimes(1);
            await user.click(screen.getByRole('button', { name: 'Filter' }));

            await waitFor(() => {
                expect(getNotifications).toHaveBeenLastCalledWith(
                    expect.objectContaining({
                        query: {
                            limit: 100,
                            include_tags: ['exec', 'completed'],
                            exclude_tags: ['alert'],
                            tag_prefix: 'exec:',
                        },
                    }),
                );
            });
        });
    });
});
