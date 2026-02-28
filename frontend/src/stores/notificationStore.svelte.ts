import {
    getNotificationsApiV1NotificationsGet,
    markNotificationReadApiV1NotificationsNotificationIdReadPut,
    markAllReadApiV1NotificationsMarkAllReadPost,
    deleteNotificationApiV1NotificationsNotificationIdDelete,
    type GetNotificationsApiV1NotificationsGetData,
    type NotificationResponse,
} from '$lib/api';
import { getErrorMessage } from '$lib/api-interceptors';

type NotificationQueryOpts = Omit<NonNullable<GetNotificationsApiV1NotificationsGetData['query']>, 'limit' | 'offset'>;

class NotificationStore {
    notifications = $state.raw<NotificationResponse[]>([]);
    loading = $state(false);
    error = $state<string | null>(null);
    unreadCount = $state(0);

    async load(limit = 20, options: NotificationQueryOpts = {}) {
        this.loading = true;
        this.error = null;
        const { data, error } = await getNotificationsApiV1NotificationsGet({
            query: {
                limit,
                include_tags: options.include_tags?.filter(Boolean),
                exclude_tags: options.exclude_tags?.filter(Boolean),
                tag_prefix: options.tag_prefix
            }
        });
        if (error) {
            this.error = getErrorMessage(error);
            this.loading = false;
            return [];
        }
        this.notifications = data.notifications;
        this.unreadCount = data.unread_count;
        this.loading = false;
        return data.notifications;
    }

    add(notification: NotificationResponse) {
        this.notifications = [notification, ...this.notifications];
        if (notification.status !== 'read') this.unreadCount++;
    }

    async markAsRead(notificationId: string) {
        const { error } = await markNotificationReadApiV1NotificationsNotificationIdReadPut({
            path: { notification_id: notificationId }
        });
        if (error) return false;
        const wasUnread = this.notifications.some(n => n.notification_id === notificationId && n.status !== 'read');
        this.notifications = this.notifications.map(n =>
            n.notification_id === notificationId ? { ...n, status: 'read' as const } : n
        );
        if (wasUnread) this.unreadCount = Math.max(0, this.unreadCount - 1);
        return true;
    }

    async markAllAsRead() {
        const { error } = await markAllReadApiV1NotificationsMarkAllReadPost({});
        if (error) return false;
        this.notifications = this.notifications.map(n => ({ ...n, status: 'read' as const }));
        this.unreadCount = 0;
        return true;
    }

    async delete(notificationId: string) {
        const { error } = await deleteNotificationApiV1NotificationsNotificationIdDelete({
            path: { notification_id: notificationId }
        });
        if (error) return false;
        const wasUnread = this.notifications.some(n => n.notification_id === notificationId && n.status !== 'read');
        this.notifications = this.notifications.filter(n => n.notification_id !== notificationId);
        if (wasUnread) this.unreadCount = Math.max(0, this.unreadCount - 1);
        return true;
    }

    clear() {
        this.notifications = [];
        this.unreadCount = 0;
    }

    refresh() {
        return this.load();
    }
}

export const notificationStore = new NotificationStore();
