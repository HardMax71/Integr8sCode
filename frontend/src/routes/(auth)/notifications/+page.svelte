<script lang="ts">
    import { toast } from 'svelte-sonner';
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { fly } from 'svelte/transition';
    import Spinner from '#components/Spinner.svelte';
    import {
        deleteNotificationApiV1NotificationsNotificationIdDeleteMutation,
        getNotificationsApiV1NotificationsGetOptions,
        getNotificationsApiV1NotificationsGetQueryKey,
        markAllReadApiV1NotificationsMarkAllReadPostMutation,
        markNotificationReadApiV1NotificationsNotificationIdReadPutMutation,
        NotificationStatus,
        type GetNotificationsApiV1NotificationsGetData,
        type NotificationResponse,
    } from '#lib/api/index.ts';
    import { Bell, Trash, Clock } from '@lucide/svelte';
    import { notificationIcon, SEVERITY_COLORS } from '#lib/notifications/display.ts';
    import { fieldTitle, formatRelativeTime } from '#lib/formatters.ts';

    let includeTagsInput = $state('');
    let excludeTagsInput = $state('');
    let tagPrefixInput = $state('');

    function parseTags(input: string): string[] {
        return input
            .split(/[\s,]+/)
            .map((s) => s.trim())
            .filter(Boolean);
    }

    let filters = $state<Omit<NonNullable<GetNotificationsApiV1NotificationsGetData['query']>, 'limit' | 'offset'>>({});

    const queryClient = useQueryClient();

    const list = createQuery(() => getNotificationsApiV1NotificationsGetOptions({ query: { limit: 100, ...filters } }));
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
            toast.success('All notifications marked as read');
            return refreshNotifications();
        },
    }));

    const remove = createMutation(() => ({
        ...deleteNotificationApiV1NotificationsNotificationIdDeleteMutation(),
        onSuccess: () => {
            toast.success('Notification deleted');
            return refreshNotifications();
        },
    }));

    function isDeleting(id: string): boolean {
        return remove.isPending && remove.variables?.path.notification_id === id;
    }

    function deleteNotification(id: string): void {
        if (isDeleting(id)) return;
        remove.mutate({ path: { notification_id: id } });
    }

    function markAsRead(notification: NotificationResponse): void {
        if (notification.status === NotificationStatus.READ) return;
        markRead.mutate({ path: { notification_id: notification.notification_id } });
    }

    function applyFilters(): void {
        filters = {
            include_tags: parseTags(includeTagsInput),
            exclude_tags: parseTags(excludeTagsInput),
            tag_prefix: tagPrefixInput.trim() || undefined,
        };
    }
</script>

{#snippet message(notification: NotificationResponse)}
    <h3 class="font-semibold">{notification.subject}</h3>
    <p class="text-sm text-fg-muted mt-1">{notification.body}</p>
{/snippet}

<div class="page max-w-5xl">
    <div class="card p-4 mb-6">
        <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div class="field">
                <label for="include-tags">{fieldTitle('include_tags')}</label>
                <input
                    id="include-tags"
                    class="w-full"
                    placeholder="e.g. execution,completed"
                    bind:value={includeTagsInput}
                />
            </div>
            <div class="field">
                <label for="exclude-tags">{fieldTitle('exclude_tags')}</label>
                <input
                    id="exclude-tags"
                    class="w-full"
                    placeholder="e.g. external_alert"
                    bind:value={excludeTagsInput}
                />
            </div>
            <div class="field">
                <label for="tag-prefix">{fieldTitle('tag_prefix')}</label>
                <input id="tag-prefix" class="w-full" placeholder="e.g. exec:" bind:value={tagPrefixInput} />
            </div>
            <div class="flex items-end">
                <button type="button" class="btn btn-primary w-full" onclick={applyFilters}>Filter</button>
            </div>
        </div>
    </div>
    <div class="flex justify-between items-center mb-8">
        <h1>Notifications</h1>
        {#if notifications.length > 0 && unreadCount > 0}
            <button type="button" onclick={() => markAllRead.mutate({})} class="btn btn-secondary-outline btn-sm">
                Mark all as read
            </button>
        {/if}
    </div>

    {#if list.isPending}
        <div class="flex justify-center items-center h-64">
            <Spinner size="xlarge" />
        </div>
    {:else if notifications.length === 0}
        <div class="card p-12 text-center">
            <Bell class="size-16 mx-auto mb-4 text-fg-subtle" />
            <h3 class="text-lg font-semibold mb-2">No notifications yet</h3>
            <p class="text-fg-muted">
                You'll see notifications here when there are updates about your executions or system events.
            </p>
        </div>
    {:else}
        <div class="space-y-3">
            {#each notifications as notification (notification.notification_id)}
                {@const NotifIcon = notificationIcon(notification.tags)}
                <article
                    in:fly={{ y: 20, duration: 300 }}
                    class={[
                        'card flex items-start gap-4 p-4',
                        notification.status !== NotificationStatus.READ && 'bg-info-soft border-info/30',
                    ]}
                >
                    <NotifIcon class="size-5 mt-1 shrink-0 {SEVERITY_COLORS[notification.severity]}" />

                    <div class="flex-1">
                        <div class="flex items-start justify-between">
                            {#if notification.status !== NotificationStatus.READ}
                                <button
                                    type="button"
                                    class="flex-1 text-left"
                                    title="Mark as read"
                                    onclick={() => markAsRead(notification)}
                                >
                                    {@render message(notification)}
                                </button>
                            {:else}
                                <div class="flex-1">{@render message(notification)}</div>
                            {/if}

                            <button
                                type="button"
                                onclick={() => deleteNotification(notification.notification_id)}
                                class="btn btn-ghost btn-sm text-danger hover:bg-danger-soft ml-4"
                                disabled={isDeleting(notification.notification_id)}
                                aria-label="Delete notification"
                            >
                                {#if isDeleting(notification.notification_id)}
                                    <Spinner size="small" />
                                {:else}
                                    <Trash class="size-4" />
                                {/if}
                            </button>
                        </div>

                        <div class="flex items-center gap-4 mt-3">
                            <span class="inline-flex items-center gap-1 text-xs text-fg-subtle">
                                <Clock class="size-4" />
                                {formatRelativeTime(notification.created_at)}
                            </span>

                            <span class="badge badge-neutral text-fg-muted">
                                {notification.channel}
                            </span>

                            <span class="badge badge-neutral {SEVERITY_COLORS[notification.severity]}">
                                {notification.severity}
                            </span>

                            {#if notification.tags.length}
                                <span class="flex flex-wrap gap-1">
                                    {#each notification.tags.slice(0, 6) as tag (tag)}
                                        <span class="badge badge-neutral border px-1.5 text-fg-muted">{tag}</span>
                                    {/each}
                                </span>
                            {/if}

                            {#if notification.status === NotificationStatus.READ}
                                <span class="text-xs text-success">{notification.status}</span>
                            {/if}
                        </div>
                    </div>
                </article>
            {/each}
        </div>
    {/if}
</div>
