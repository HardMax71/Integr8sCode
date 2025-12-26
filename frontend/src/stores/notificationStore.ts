import { writable, derived } from 'svelte/store';
import {
    getNotificationsApiV1NotificationsGet,
    markNotificationReadApiV1NotificationsNotificationIdReadPut,
    markAllReadApiV1NotificationsMarkAllReadPost,
    deleteNotificationApiV1NotificationsNotificationIdDelete,
    type NotificationResponse,
} from '$lib/api';

interface State {
    notifications: NotificationResponse[];
    loading: boolean;
    error: string | null;
}

function createNotificationStore() {
    const { subscribe, set, update } = writable<State>({
        notifications: [],
        loading: false,
        error: null
    });

    return {
        subscribe,

        async load(limit = 20, options: { include_tags?: string[]; exclude_tags?: string[]; tag_prefix?: string } = {}) {
            update(s => ({ ...s, loading: true, error: null }));
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
                update(s => ({ ...s, loading: false, error: msg }));
                return [];
            }
            set({ notifications: data?.notifications ?? [], loading: false, error: null });
            return data?.notifications ?? [];
        },

        add(notification: NotificationResponse) {
            update(s => ({
                ...s,
                notifications: [notification, ...s.notifications].slice(0, 100)
            }));
        },

        async markAsRead(notificationId: string) {
            const { error } = await markNotificationReadApiV1NotificationsNotificationIdReadPut({
                path: { notification_id: notificationId }
            });
            if (error) return false;
            update(s => ({
                ...s,
                notifications: s.notifications.map(n =>
                    n.notification_id === notificationId ? { ...n, status: 'read' as const } : n
                )
            }));
            return true;
        },

        async markAllAsRead() {
            const { error } = await markAllReadApiV1NotificationsMarkAllReadPost({});
            if (error) return false;
            update(s => ({
                ...s,
                notifications: s.notifications.map(n => ({ ...n, status: 'read' as const }))
            }));
            return true;
        },

        async delete(notificationId: string) {
            const { error } = await deleteNotificationApiV1NotificationsNotificationIdDelete({
                path: { notification_id: notificationId }
            });
            if (error) return false;
            update(s => ({
                ...s,
                notifications: s.notifications.filter(n => n.notification_id !== notificationId)
            }));
            return true;
        },

        clear() {
            update(s => ({ ...s, notifications: [] }));
        },

        refresh() {
            return this.load();
        }
    };
}

export const notificationStore = createNotificationStore();
export const unreadCount = derived(notificationStore, s => s.notifications.filter(n => n.status !== 'read').length);
export const notifications = derived(notificationStore, s => s.notifications);
export const loading = derived(notificationStore, s => s.loading);
