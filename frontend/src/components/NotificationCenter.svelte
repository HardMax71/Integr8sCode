<script lang="ts">
    import { type Component } from 'svelte';
    import { fly } from 'svelte/transition';
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { authStore } from '#stores/auth.svelte.ts';
    import { goto } from '$app/navigation';
    import { notificationStream } from '#lib/notifications/stream.svelte.ts';
    import {
        getNotificationsApiV1NotificationsGetOptions,
        getNotificationsApiV1NotificationsGetQueryKey,
        markAllReadApiV1NotificationsMarkAllReadPostMutation,
        markNotificationReadApiV1NotificationsNotificationIdReadPutMutation,
        type NotificationResponse,
    } from '#lib/api/index.ts';
    import { Bell, CircleAlert, TriangleAlert, CircleCheck, Info } from '@lucide/svelte';
    import Spinner from '#components/Spinner.svelte';
    import { formatRelativeTime } from '#lib/formatters.ts';

    const AUTO_READ_DELAY_MS = 2000;

    let showDropdown = $state(false);

    function getNotificationIcon(tags: string[] = []): Component {
        const set = new Set(tags || []);
        if (set.has('failed') || set.has('error') || set.has('security')) return CircleAlert;
        if (set.has('timeout') || set.has('warning')) return TriangleAlert;
        if (set.has('completed') || set.has('success')) return CircleCheck;
        return Info;
    }

    const priorityColors = {
        low: 'text-fg-muted dark:text-dark-fg-muted',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400',
    };

    const queryClient = useQueryClient();
    const signedIn = $derived(authStore.isAuthenticated === true);

    const list = createQuery(() => ({
        ...getNotificationsApiV1NotificationsGetOptions({ query: { limit: 20 } }),
        enabled: signedIn,
    }));
    let notifications = $derived(list.data?.notifications ?? []);
    let unreadCount = $derived(list.data?.unread_count ?? 0);

    function refreshNotifications(): Promise<void> {
        return queryClient.invalidateQueries({ queryKey: getNotificationsApiV1NotificationsGetQueryKey() });
    }

    const markRead = createMutation(() => ({
        ...markNotificationReadApiV1NotificationsNotificationIdReadPutMutation(),
        onSuccess: refreshNotifications,
    }));

    const markAllRead = createMutation(() => ({
        ...markAllReadApiV1NotificationsMarkAllReadPostMutation(),
        onSuccess: () => {
            showDropdown = false;
            return refreshNotifications();
        },
    }));

    $effect(() => {
        if (!signedIn) return;
        notificationStream.connect(() => void refreshNotifications());
        return () => {
            notificationStream.disconnect();
        };
    });

    $effect(() => {
        if (!showDropdown || unreadCount === 0) return;
        const timeout = setTimeout(() => {
            if (!showDropdown) return;
            notifications.slice(0, 5).forEach(markAsRead);
        }, AUTO_READ_DELAY_MS);
        return () => clearTimeout(timeout);
    });

    function markAsRead(notification: NotificationResponse): void {
        if (notification.status === 'read') return;
        markRead.mutate({ path: { notification_id: notification.notification_id } });
    }

    function handleNotificationClick(notification: NotificationResponse): void {
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

    function toggleDropdown(): void {
        showDropdown = !showDropdown;
    }

    let notificationPermission = $state(
        typeof window !== 'undefined' && 'Notification' in window ? Notification.permission : 'denied',
    );

    async function requestNotificationPermission(): Promise<void> {
        if (!('Notification' in window)) return;
        const result = await Notification.requestPermission();
        notificationPermission = result;
    }
</script>

<div class="relative z-40">
    <button type="button" onclick={toggleDropdown} class="btn btn-ghost btn-icon relative" aria-label="Notifications">
        <Bell class="w-5 h-5" />
        {#if unreadCount > 0}
            <span
                class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center"
            >
                {unreadCount > 9 ? '9+' : unreadCount}
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
                    {#if unreadCount > 0}
                        <button
                            type="button"
                            onclick={() => markAllRead.mutate({})}
                            class="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                        >
                            Mark all as read
                        </button>
                    {/if}
                </div>
                {#if notificationPermission === 'default'}
                    <button
                        type="button"
                        onclick={requestNotificationPermission}
                        class="mt-2 w-full text-xs text-fg-muted dark:text-dark-fg-muted hover:text-blue-600 dark:hover:text-blue-400 flex items-center justify-center gap-1"
                    >
                        <Bell class="w-3 h-3" />
                        Enable desktop notifications
                    </button>
                {/if}
            </div>

            <div class="max-h-96 overflow-y-auto">
                {#if list.isPending && signedIn}
                    <div class="p-8 text-center">
                        <Spinner size="small" />
                    </div>
                {:else if notifications.length === 0}
                    <div class="p-8 text-center text-fg-muted dark:text-dark-fg-muted">No notifications yet</div>
                {:else}
                    {#each notifications as notification}
                        {@const NotifIcon = getNotificationIcon(notification.tags)}
                        <div
                            class="p-4 border-b border-border-default/50 dark:border-dark-border-default hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover cursor-pointer transition-colors"
                            class:bg-blue-50={notification.status !== 'read'}
                            class:dark:bg-blue-900={notification.status !== 'read'}
                            onclick={() => handleNotificationClick(notification)}
                            onkeydown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    handleNotificationClick(notification);
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
                                        {formatRelativeTime(notification.created_at)}
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
                    type="button"
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
