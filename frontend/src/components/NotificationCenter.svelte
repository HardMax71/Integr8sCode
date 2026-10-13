<script lang="ts">
    import { match, resolve } from '$app/paths';
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { goto } from '$app/navigation';
    import { notificationStream } from '#lib/notifications/stream.svelte.ts';
    import {
        getNotificationsApiV1NotificationsGetOptions,
        getNotificationsApiV1NotificationsGetQueryKey,
        markAllReadApiV1NotificationsMarkAllReadPostMutation,
        markNotificationReadApiV1NotificationsNotificationIdReadPutMutation,
        NotificationStatus,
        type NotificationResponse,
    } from '#lib/api/index.ts';
    import { notificationIcon, SEVERITY_COLORS } from '#lib/notifications/display.ts';
    import { Bell } from '@lucide/svelte';
    import Spinner from '#components/Spinner.svelte';
    import { Popover } from 'bits-ui';
    import { formatRelativeTime } from '#lib/formatters.ts';

    const AUTO_READ_DELAY_MS = 2000;

    let showDropdown = $state(false);

    const queryClient = useQueryClient();
    const list = createQuery(() => getNotificationsApiV1NotificationsGetOptions({ query: { limit: 20 } }));
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
        if (notification.status === NotificationStatus.READ) return;
        markRead.mutate({ path: { notification_id: notification.notification_id } });
    }

    function handleNotificationClick(notification: NotificationResponse): void {
        markAsRead(notification);
        if (notification.action_url) void openPage(notification.action_url);
    }

    // Only a page of this app opens; an API path or an outside URL in action_url matches no route
    async function openPage(url: string): Promise<void> {
        const route = await match(url);
        if (!route) return;
        showDropdown = false;
        await goto(resolve(route.id));
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

<Popover.Root bind:open={showDropdown}>
    <Popover.Trigger class="btn btn-ghost btn-icon relative" aria-label="Notifications">
        <Bell class="w-5 h-5" />
        {#if unreadCount > 0}
            <span
                class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center"
            >
                {unreadCount > 9 ? '9+' : unreadCount}
            </span>
        {/if}
    </Popover.Trigger>

    <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} class="floating-panel w-96 p-0">
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
                {#if list.isPending}
                    <div class="p-8 text-center">
                        <Spinner size="small" />
                    </div>
                {:else if notifications.length === 0}
                    <div class="p-8 text-center text-fg-muted dark:text-dark-fg-muted">No notifications yet</div>
                {:else}
                    {#each notifications as notification (notification.notification_id)}
                        {@const NotifIcon = notificationIcon(notification.tags)}
                        <button
                            type="button"
                            class="block w-full text-left p-4 border-b border-border-default/50 dark:border-dark-border-default hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover cursor-pointer transition-colors"
                            class:bg-blue-50={notification.status !== NotificationStatus.READ}
                            class:dark:bg-blue-900={notification.status !== NotificationStatus.READ}
                            onclick={() => handleNotificationClick(notification)}
                            aria-label="View notification: {notification.subject}"
                        >
                            <span class="flex items-start space-x-3">
                                <span class={`mt-1 ${SEVERITY_COLORS[notification.severity]}`}>
                                    <NotifIcon class="w-5 h-5" />
                                </span>
                                <span class="flex-1 min-w-0">
                                    <span class="block font-medium text-sm">
                                        {notification.subject}
                                    </span>
                                    <span class="block text-sm text-fg-muted dark:text-dark-fg-muted mt-1">
                                        {notification.body}
                                    </span>
                                    <span class="block text-xs text-fg-subtle dark:text-dark-fg-subtle mt-2">
                                        {formatRelativeTime(notification.created_at)}
                                    </span>
                                </span>
                                {#if notification.status !== NotificationStatus.READ}
                                    <span class="w-2 h-2 bg-blue-500 rounded-full mt-2"></span>
                                {/if}
                            </span>
                        </button>
                    {/each}
                {/if}
            </div>

            <div class="p-3 border-t border-border-default dark:border-dark-border-default">
                <button
                    type="button"
                    onclick={() => {
                        showDropdown = false;
                        goto(resolve('/(auth)/notifications'));
                    }}
                    class="block w-full text-center text-sm text-blue-600 dark:text-blue-400 hover:underline bg-transparent border-none cursor-pointer"
                >
                    View all notifications
                </button>
            </div>
        </Popover.Content>
    </Popover.Portal>
</Popover.Root>
