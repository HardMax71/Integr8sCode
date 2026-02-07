import {
    getNotificationsApiV1NotificationsGet,
    markNotificationReadApiV1NotificationsNotificationIdReadPut,
    markAllReadApiV1NotificationsMarkAllReadPost,
    deleteNotificationApiV1NotificationsNotificationIdDelete,
    type NotificationResponse,
} from '$lib/api';

class NotificationStore {
    notifications = $state<NotificationResponse[]>([]);
    loading = $state(false);
    error = $state<string | null>(null);
    unreadCount = $derived(this.notifications.filter(n => n.status !== 'read').length);

    async load(limit = 20, options: { include_tags?: string[]; exclude_tags?: string[]; tag_prefix?: string } = {}) {
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
            const msg = (error as { detail?: Array<{ msg?: string }> }).detail?.[0]?.msg
                ?? JSON.stringify(error);
            this.loading = false;
            this.error = msg;
            return [];
        }
        this.notifications = data?.notifications ?? [];
        this.loading = false;
        this.error = null;
        return data?.notifications ?? [];
    }

    add(notification: NotificationResponse) {
        this.notifications = [notification, ...this.notifications].slice(0, 100);
    }

    async markAsRead(notificationId: string) {
        const { error } = await markNotificationReadApiV1NotificationsNotificationIdReadPut({
            path: { notification_id: notificationId }
        });
        if (error) return false;
        this.notifications = this.notifications.map(n =>
            n.notification_id === notificationId ? { ...n, status: 'read' as const } : n
        );
        return true;
    }

    async markAllAsRead() {
        const { error } = await markAllReadApiV1NotificationsMarkAllReadPost({});
        if (error) return false;
        this.notifications = this.notifications.map(n => ({ ...n, status: 'read' as const }));
        return true;
    }

    async delete(notificationId: string) {
        const { error } = await deleteNotificationApiV1NotificationsNotificationIdDelete({
            path: { notification_id: notificationId }
        });
        if (error) return false;
        this.notifications = this.notifications.filter(n => n.notification_id !== notificationId);
        return true;
    }

    clear() {
        this.notifications = [];
    }

    refresh() {
        return this.load();
    }
}

export const notificationStore = new NotificationStore();
