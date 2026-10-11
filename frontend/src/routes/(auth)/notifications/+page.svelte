<script lang="ts">
    import { type Component } from 'svelte';
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
        type GetNotificationsApiV1NotificationsGetData,
        type NotificationResponse,
    } from '#lib/api/index.ts';
    import { Bell, Trash, Clock, CircleCheck, CircleAlert, Info } from '@lucide/svelte';
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
        if (notification.status === 'read') return;
        markRead.mutate({ path: { notification_id: notification.notification_id } });
    }

    function applyFilters(): void {
        filters = {
            include_tags: parseTags(includeTagsInput),
            exclude_tags: parseTags(excludeTagsInput),
            tag_prefix: tagPrefixInput.trim() || undefined,
        };
    }

    // New unified notification rendering: derive icons from tags and colors from severity
    const severityColors: Record<string, string> = {
        low: 'text-fg-muted dark:text-dark-fg-muted',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400',
    };

    function getNotificationIcon(tags: string[] = []): Component {
        const set = new Set(tags || []);
        if (set.has('failed') || set.has('error') || set.has('security')) return CircleAlert;
        if (set.has('timeout') || set.has('warning')) return Clock;
        if (set.has('completed') || set.has('success')) return CircleCheck;
        return Info;
    }
</script>

{#snippet message(notification: NotificationResponse)}
    <h3 class="font-semibold text-fg-default dark:text-dark-fg-default">{notification.subject}</h3>
    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">{notification.body}</p>
{/snippet}

<div class="min-h-screen bg-bg-default dark:bg-dark-bg-default">
    <div class="container mx-auto px-4 py-8 max-w-5xl">
        <div class="card p-4 mb-6">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div>
                    <label for="include-tags" class="block text-sm text-fg-muted dark:text-dark-fg-muted mb-1"
                        >{fieldTitle('include_tags')}</label
                    >
                    <input
                        id="include-tags"
                        class="input input-bordered w-full"
                        placeholder="e.g. execution,completed"
                        bind:value={includeTagsInput}
                    />
                </div>
                <div>
                    <label for="exclude-tags" class="block text-sm text-fg-muted dark:text-dark-fg-muted mb-1"
                        >{fieldTitle('exclude_tags')}</label
                    >
                    <input
                        id="exclude-tags"
                        class="input input-bordered w-full"
                        placeholder="e.g. external_alert"
                        bind:value={excludeTagsInput}
                    />
                </div>
                <div>
                    <label for="tag-prefix" class="block text-sm text-fg-muted dark:text-dark-fg-muted mb-1"
                        >{fieldTitle('tag_prefix')}</label
                    >
                    <input
                        id="tag-prefix"
                        class="input input-bordered w-full"
                        placeholder="e.g. exec:"
                        bind:value={tagPrefixInput}
                    />
                </div>
                <div class="flex items-end">
                    <button type="button" class="btn btn-primary w-full" onclick={applyFilters}>Filter</button>
                </div>
            </div>
        </div>
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">Notifications</h1>
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
            <div class="card">
                <div class="p-12 text-center">
                    <div
                        class="w-20 h-20 mx-auto mb-4 text-fg-subtle dark:text-dark-fg-subtle flex items-center justify-center"
                    >
                        <Bell class="w-16 h-16" />
                    </div>
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-2">
                        No notifications yet
                    </h3>
                    <p class="text-fg-muted dark:text-dark-fg-muted">
                        You'll see notifications here when there are updates about your executions or system events.
                    </p>
                </div>
            </div>
        {:else}
            <div class="space-y-3">
                {#each notifications as notification (notification.notification_id)}
                    {@const NotifIcon = getNotificationIcon(notification.tags)}
                    <article
                        in:fly={{ y: 20, duration: 300 }}
                        class="card transition-all duration-200 {notification.status !== 'read'
                            ? 'bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800/50'
                            : ''}"
                    >
                        <div class="p-4">
                            <div class="flex items-start gap-4">
                                <div class="mt-1 {severityColors[notification.severity || 'medium']}">
                                    <NotifIcon class="w-5 h-5" />
                                </div>

                                <div class="flex-1">
                                    <div class="flex items-start justify-between">
                                        {#if notification.status !== 'read'}
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
                                            class="btn btn-ghost btn-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 ml-4"
                                            disabled={isDeleting(notification.notification_id)}
                                            aria-label="Delete notification"
                                        >
                                            {#if isDeleting(notification.notification_id)}
                                                <Spinner size="small" />
                                            {:else}
                                                <Trash class="w-4 h-4" />
                                            {/if}
                                        </button>
                                        {#if (notification.tags || []).some((t) => t.startsWith('exec:'))}
                                            {@const execTag = (notification.tags || []).find((t) =>
                                                t.startsWith('exec:'),
                                            )}
                                            {#if execTag}
                                                <a
                                                    href={`/editor?execution=${execTag.split(':')[1]}`}
                                                    class="btn btn-ghost btn-sm text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 ml-2"
                                                >
                                                    View result
                                                </a>
                                            {/if}
                                        {/if}
                                    </div>

                                    <div class="flex items-center gap-4 mt-3">
                                        <span
                                            class="inline-flex items-center gap-1 text-xs text-fg-subtle dark:text-dark-fg-subtle"
                                        >
                                            <Clock class="w-4 h-4" />
                                            {formatRelativeTime(notification.created_at)}
                                        </span>

                                        <span
                                            class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 dark:bg-neutral-800 text-fg-muted dark:text-dark-fg-muted"
                                        >
                                            {notification.channel}
                                        </span>

                                        {#if notification.severity}
                                            <span
                                                class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 dark:bg-neutral-800 {severityColors[
                                                    notification.severity
                                                ] || severityColors.medium}"
                                            >
                                                {notification.severity}
                                            </span>
                                        {/if}

                                        {#if notification.tags && notification.tags.length}
                                            <span class="flex flex-wrap gap-1">
                                                {#each notification.tags.slice(0, 6) as tag}
                                                    <span
                                                        class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-100 dark:bg-neutral-800 text-fg-muted dark:text-dark-fg-muted border border-neutral-200 dark:border-neutral-700"
                                                        >{tag}</span
                                                    >
                                                {/each}
                                            </span>
                                        {/if}

                                        {#if notification.status === 'read'}
                                            <span class="text-xs text-green-600 dark:text-green-400"
                                                >{notification.status}</span
                                            >
                                        {/if}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </article>
                {/each}
            </div>
        {/if}
    </div>
</div>
