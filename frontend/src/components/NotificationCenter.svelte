<script lang="ts">
    import { onDestroy, type Component } from 'svelte';
    import { fly } from 'svelte/transition';
    import { authStore } from '$stores/auth.svelte';
    import { goto } from '@mateothegreat/svelte5-router';
    import { notificationStore } from '$stores/notificationStore.svelte';
    import { notificationStream } from '$lib/notifications/stream.svelte';
    import type { NotificationResponse } from '$lib/api';
    import { Bell, AlertCircle, AlertTriangle, CircleCheck, Info } from '@lucide/svelte';

    let showDropdown = $state(false);
    let hasLoadedInitialData = false;
    let autoMarkTimeout: ReturnType<typeof setTimeout> | null = null;

    function getNotificationIcon(tags: string[] = []): Component {
        const set = new Set(tags || []);
        if (set.has('failed') || set.has('error') || set.has('security')) return AlertCircle;
        if (set.has('timeout') || set.has('warning')) return AlertTriangle;
        if (set.has('completed') || set.has('success')) return CircleCheck;
        return Info;
    }

    const priorityColors = {
        low: 'text-fg-muted dark:text-dark-fg-muted',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400'
    };

    // Reactive connection based on auth state
    $effect(() => {
        if (authStore.isAuthenticated) {
            if (!hasLoadedInitialData) {
                hasLoadedInitialData = true;
                notificationStore.load(20).then(() => {
                    notificationStream.connect((data) => notificationStore.add(data));
                }).catch((err) => console.error('Failed to load notifications:', err));
            }
        } else {
            notificationStream.disconnect();
            hasLoadedInitialData = false;
            notificationStore.clear();
        }
    });

    onDestroy(() => {
        notificationStream.disconnect();
        if (autoMarkTimeout) clearTimeout(autoMarkTimeout);
    });

    async function markAsRead(notification: NotificationResponse): Promise<void> {
        if (notification.status === 'read') return;
        await notificationStore.markAsRead(notification.notification_id);
    }

    async function markAllAsRead(): Promise<void> {
        const success = await notificationStore.markAllAsRead();
        if (success) {
            showDropdown = false;
        }
    }

    function toggleDropdown(): void {
        showDropdown = !showDropdown;
        if (autoMarkTimeout) { clearTimeout(autoMarkTimeout); autoMarkTimeout = null; }

        if (showDropdown && notificationStore.unreadCount > 0) {
            autoMarkTimeout = setTimeout(() => {
                if (!showDropdown) return;
                autoMarkTimeout = null;
                notificationStore.notifications.slice(0, 5).forEach(n => {
                    if (n.status !== 'read') {
                        markAsRead(n).catch(() => {});
                    }
                });
            }, 2000);
        }
    }

    function formatTime(timestamp: string): string {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now.getTime() - date.getTime();

        if (diff < 60000) return 'just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return date.toLocaleDateString();
    }

    let notificationPermission = $state(
        typeof window !== 'undefined' && 'Notification' in window
            ? Notification.permission
            : 'denied'
    );

    async function requestNotificationPermission(): Promise<void> {
        if (!('Notification' in window)) return;
        const result = await Notification.requestPermission();
        notificationPermission = result;
    }
</script>

<div class="relative z-40">
    <button
        onclick={toggleDropdown}
        class="btn btn-ghost btn-icon relative"
        aria-label="Notifications"
    >
        <Bell class="w-5 h-5" />
        {#if notificationStore.unreadCount > 0}
            <span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center">
                {notificationStore.unreadCount > 9 ? '9+' : notificationStore.unreadCount}
            </span>
        {/if}
    </button>

    {#if showDropdown}
        <div
            class="absolute right-0 mt-2 w-96 bg-surface-overlay dark:bg-dark-surface-overlay rounded-lg shadow-lg border border-border-default dark:border-dark-border-default z-50"
            transition:fly={{ y: -10, duration: 200 }}
        >
            <div class="p-4 border-b border-border-default dark:border-dark-border-default">
                <div class="flex justify-between items-center">
                    <h3 class="font-semibold text-lg">Notifications</h3>
                    {#if notificationStore.unreadCount > 0}
                        <button
                            onclick={markAllAsRead}
                            class="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                        >
                            Mark all as read
                        </button>
                    {/if}
                </div>
                {#if notificationPermission === 'default'}
                    <button
                        onclick={requestNotificationPermission}
                        class="mt-2 w-full text-xs text-fg-muted dark:text-dark-fg-muted hover:text-blue-600 dark:hover:text-blue-400 flex items-center justify-center gap-1"
                    >
                        <Bell class="w-3 h-3" />
                        Enable desktop notifications
                    </button>
                {/if}
            </div>

            <div class="max-h-96 overflow-y-auto">
                {#if notificationStore.loading}
                    <div class="p-8 text-center">
                        <span class="loading loading-spinner loading-sm"></span>
                    </div>
                {:else if notificationStore.notifications.length === 0}
                    <div class="p-8 text-center text-fg-muted dark:text-dark-fg-muted">
                        No notifications yet
                    </div>
                {:else}
                    {#each notificationStore.notifications as notification}
                        {@const NotifIcon = getNotificationIcon(notification.tags)}
                        <div
                            class="p-4 border-b border-border-default/50 dark:border-dark-border-default hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover cursor-pointer transition-colors"
                            class:bg-blue-50={notification.status !== 'read'}
                            class:dark:bg-blue-900={notification.status !== 'read'}
                            onclick={() => {
                                markAsRead(notification);
                                if (notification.action_url) {
                                    if (notification.action_url.startsWith('/')) {
                                        showDropdown = false;
                                        goto(notification.action_url);
                                    } else {
                                        window.location.href = notification.action_url;
                                    }
                                }
                            }}
                            onkeydown={(e) => {
                                if (e.key === 'Enter') {
                                    markAsRead(notification);
                                    if (notification.action_url) {
                                        if (notification.action_url.startsWith('/')) {
                                            showDropdown = false;
                                            goto(notification.action_url);
                                        } else {
                                            window.location.href = notification.action_url;
                                        }
                                    }
                                }
                            }}
                            tabindex="0"
                            role="button"
                            aria-label="View notification: {notification.subject}"
                        >
                            <div class="flex items-start space-x-3">
                                <div class={`mt-1 ${priorityColors[notification.severity || 'medium']}`}>
                                    <NotifIcon class="w-5 h-5" />
                                </div>
                                <div class="flex-1 min-w-0">
                                    <p class="font-medium text-sm">
                                        {notification.subject}
                                    </p>
                                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">
                                        {notification.body}
                                    </p>
                                    <p class="text-xs text-fg-subtle dark:text-dark-fg-subtle mt-2">
                                        {formatTime(notification.created_at)}
                                    </p>
                                </div>
                                {#if notification.status !== 'read'}
                                    <div class="w-2 h-2 bg-blue-500 rounded-full mt-2"></div>
                                {/if}
                            </div>
                        </div>
                    {/each}
                {/if}
            </div>

            <div class="p-3 border-t border-border-default dark:border-dark-border-default">
                <button
                    onclick={() => {
                        showDropdown = false;
                        goto('/notifications');
                    }}
                    class="block w-full text-center text-sm text-blue-600 dark:text-blue-400 hover:underline bg-transparent border-none cursor-pointer"
                >
                    View all notifications
                </button>
            </div>
        </div>
    {/if}
</div>
