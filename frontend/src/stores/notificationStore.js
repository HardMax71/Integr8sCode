import { writable, derived } from 'svelte/store';
import { api } from '../lib/api';

// Create the main notification store
function createNotificationStore() {
    const { subscribe, set, update } = writable({
        notifications: [],
        loading: false,
        error: null
    });

    return {
        subscribe,
        
        // Load notifications from API
        async load(limit = 20, options = {}) {
            update(state => ({ ...state, loading: true, error: null }));
            try {
                const params = new URLSearchParams({ limit: String(limit) });
                if (options.include_tags && Array.isArray(options.include_tags)) {
                    for (const t of options.include_tags.filter(Boolean)) params.append('include_tags', t);
                }
                if (options.exclude_tags && Array.isArray(options.exclude_tags)) {
                    for (const t of options.exclude_tags.filter(Boolean)) params.append('exclude_tags', t);
                }
                if (options.tag_prefix) params.append('tag_prefix', options.tag_prefix);
                const qs = params.toString();
                const response = await api.get(`/api/v1/notifications?${qs}`);
                set({
                    notifications: response.notifications || [],
                    loading: false,
                    error: null
                });
                return response.notifications || [];
            } catch (error) {
                update(state => ({
                    ...state,
                    loading: false,
                    error: error.message
                }));
                console.error('Failed to load notifications:', error);
                return [];
            }
        },

        // Add a new notification
        add(notification) {
            update(state => ({
                ...state,
                notifications: [notification, ...state.notifications].slice(0, 100)
            }));
        },

        // Mark notification as read
        async markAsRead(notificationId) {
            try {
                await api.put(`/api/v1/notifications/${notificationId}/read`);
                update(state => ({
                    ...state,
                    notifications: state.notifications.map(n =>
                        n.notification_id === notificationId
                            ? { ...n, status: 'read', read_at: new Date().toISOString() }
                            : n
                    )
                }));
                return true;
            } catch (error) {
                console.error('Failed to mark notification as read:', error);
                return false;
            }
        },

        // Mark all notifications as read
        async markAllAsRead() {
            try {
                await api.post('/api/v1/notifications/mark-all-read');
                update(state => ({
                    ...state,
                    notifications: state.notifications.map(n => ({
                        ...n,
                        status: 'read',
                        read_at: new Date().toISOString()
                    }))
                }));
                return true;
            } catch (error) {
                console.error('Failed to mark all as read:', error);
                return false;
            }
        },

        // Delete a notification
        async delete(notificationId) {
            try {
                await api.delete(`/api/v1/notifications/${notificationId}`);
                update(state => ({
                    ...state,
                    notifications: state.notifications.filter(n => n.notification_id !== notificationId)
                }));
                return true;
            } catch (error) {
                console.error('Failed to delete notification:', error);
                return false;
            }
        },

        // Clear all notifications from store (not from backend)
        clear() {
            update(state => ({ ...state, notifications: [] }));
        },

        // Refresh notifications from backend
        async refresh() {
            return this.load();
        }
    };
}

// Create the store instance
export const notificationStore = createNotificationStore();

// Derived store for unread count
export const unreadCount = derived(
    notificationStore,
    $notificationStore => $notificationStore.notifications.filter(
        n => n.status !== 'read'
    ).length
);

// Derived store for just the notifications array
export const notifications = derived(
    notificationStore,
    $notificationStore => $notificationStore.notifications
);
