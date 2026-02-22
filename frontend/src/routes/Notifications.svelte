<script lang="ts">
    import { onMount, type Component } from 'svelte';
    import { toast } from 'svelte-sonner';
    import { notificationStore } from '$stores/notificationStore.svelte';
    import { fly } from 'svelte/transition';
    import Spinner from '$components/Spinner.svelte';
    import type { NotificationResponse } from '$lib/api';
    import { Bell, Trash2, Clock, CircleCheck, AlertCircle, Info } from '@lucide/svelte';

    let loading = $state(false);
    let deleting = $state<Record<string, boolean>>({});
    let includeTagsInput = $state('');
    let excludeTagsInput = $state('');
    let prefixInput = $state('');
    
    
    onMount(async () => {
        loading = true;
        await notificationStore.load(100);
        loading = false;
    });
    
    async function deleteNotification(id: string): Promise<void> {
        if (deleting[id]) return;

        deleting[id] = true;
        const success = await notificationStore.delete(id);
        if (success) {
            toast.success('Notification deleted');
        } else {
            toast.error('Failed to delete notification');
        }
        deleting[id] = false;
    }

    async function markAsRead(notification: NotificationResponse): Promise<void> {
        if (notification.status === 'read') return;
        await notificationStore.markAsRead(notification.notification_id);
    }

    async function markAllAsRead(): Promise<void> {
        const success = await notificationStore.markAllAsRead();
        if (success) {
            toast.success('All notifications marked as read');
        } else {
            toast.error('Failed to mark all as read');
        }
    }

    function parseTags(input: string): string[] {
        return input
            .split(/[\s,]+/)
            .map(s => s.trim())
            .filter(Boolean);
    }

    async function applyFilters(): Promise<void> {
        loading = true;
        const include_tags = parseTags(includeTagsInput);
        const exclude_tags = parseTags(excludeTagsInput);
        const tag_prefix = prefixInput.trim() || undefined;
        await notificationStore.load(100, { include_tags, exclude_tags, tag_prefix });
        loading = false;
    }

    function formatTimestamp(timestamp: string): string {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins} minutes ago`;
        if (diffHours < 24) return `${diffHours} hours ago`;
        if (diffDays < 7) return `${diffDays} days ago`;

        return date.toLocaleDateString();
    }

    // New unified notification rendering: derive icons from tags and colors from severity
    const severityColors: Record<string, string> = {
        low: 'text-fg-muted dark:text-dark-fg-muted',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400'
    };

    function getNotificationIcon(tags: string[] = []): Component {
        const set = new Set(tags || []);
        if (set.has('failed') || set.has('error') || set.has('security')) return AlertCircle;
        if (set.has('timeout') || set.has('warning')) return Clock;
        if (set.has('completed') || set.has('success')) return CircleCheck;
        return Info;
    }
</script>

<div class="min-h-screen bg-bg-default dark:bg-dark-bg-default">
    <div class="container mx-auto px-4 py-8 max-w-5xl">
        <div class="card p-4 mb-6">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div>
                    <label for="include-tags" class="block text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Include tags</label>
                    <input id="include-tags" class="input input-bordered w-full" placeholder="e.g. execution,completed"
                           bind:value={includeTagsInput}>
                </div>
                <div>
                    <label for="exclude-tags" class="block text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Exclude tags</label>
                    <input id="exclude-tags" class="input input-bordered w-full" placeholder="e.g. external_alert"
                           bind:value={excludeTagsInput}>
                </div>
                <div>
                    <label for="tag-prefix" class="block text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Tag prefix</label>
                    <input id="tag-prefix" class="input input-bordered w-full" placeholder="e.g. exec:"
                           bind:value={prefixInput}>
                </div>
                <div class="flex items-end">
                    <button type="button" class="btn btn-primary w-full" onclick={applyFilters}>Filter</button>
                </div>
            </div>
        </div>
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">Notifications</h1>
            {#if notificationStore.notifications.length > 0 && notificationStore.unreadCount > 0}
                <button type="button"
                    onclick={markAllAsRead}
                    class="btn btn-secondary-outline btn-sm"
                >
                    Mark all as read
                </button>
            {/if}
        </div>
        
        {#if loading}
            <div class="flex justify-center items-center h-64">
                <Spinner size="xlarge" />
            </div>
        {:else if notificationStore.notifications.length === 0}
            <div class="card">
                <div class="p-12 text-center">
                    <div class="w-20 h-20 mx-auto mb-4 text-fg-subtle dark:text-dark-fg-subtle flex items-center justify-center">
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
                {#each notificationStore.notifications as notification (notification.notification_id)}
                    {@const NotifIcon = getNotificationIcon(notification.tags)}
                    <div
                        in:fly={{ y: 20, duration: 300 }}
                        class="card transition-all duration-200 cursor-pointer {notification.status !== 'read' ? 'bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800/50' : ''}"
                        onclick={() => markAsRead(notification)}
                        onkeydown={(e) => e.key === 'Enter' && markAsRead(notification)}
                        role="button"
                        tabindex="0"
                        aria-label="Mark notification as read"
                    >
                        <div class="p-4">
                            <div class="flex items-start gap-4">
                                <div class="mt-1 {severityColors[notification.severity || 'medium']}">
                                    <NotifIcon class="w-5 h-5" />
                                </div>
                                
                                <div class="flex-1">
                                    <div class="flex items-start justify-between">
                                        <div class="flex-1">
                                            <h3 class="font-semibold text-fg-default dark:text-dark-fg-default">
                                                {notification.subject}
                                            </h3>
                                            <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">
                                                {notification.body}
                                            </p>
                                        </div>
                                        
                                        <button type="button"
                                            onclick={(e) => { e.stopPropagation(); deleteNotification(notification.notification_id); }}
                                            class="btn btn-ghost btn-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 ml-4"
                                            disabled={deleting[notification.notification_id]}
                                            aria-label="Delete notification"
                                        >
                                            {#if deleting[notification.notification_id]}
                                                <Spinner size="small" />
                                            {:else}
                                                <Trash2 class="w-4 h-4" />
                                            {/if}
                                        </button>
                                        {#if (notification.tags || []).some(t => t.startsWith('exec:'))}
                                            {@const execTag = (notification.tags || []).find(t => t.startsWith('exec:'))}
                                            {#if execTag}
                                                <a
                                                    href={`/editor?execution=${execTag.split(':')[1]}`}
                                                    class="btn btn-ghost btn-sm text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 ml-2"
                                                    onclick={(e) => e.stopPropagation()}
                                                >
                                                    View result
                                                </a>
                                            {/if}
                                        {/if}
                                    </div>
                                    
                                    <div class="flex items-center gap-4 mt-3">
                                        <span class="inline-flex items-center gap-1 text-xs text-fg-subtle dark:text-dark-fg-subtle">
                                            <Clock class="w-4 h-4" />
                                            {formatTimestamp(notification.created_at)}
                                        </span>
                                        
                                        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 dark:bg-neutral-800 text-fg-muted dark:text-dark-fg-muted">
                                            {notification.channel}
                                        </span>
                                        
                                        {#if notification.severity}
                                            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 dark:bg-neutral-800 {severityColors[notification.severity] || severityColors.medium}">
                                                {notification.severity}
                                            </span>
                                        {/if}
                                        
                                        {#if notification.tags && notification.tags.length}
                                            <span class="flex flex-wrap gap-1">
                                                {#each notification.tags.slice(0,6) as tag}
                                                    <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-100 dark:bg-neutral-800 text-fg-muted dark:text-dark-fg-muted border border-neutral-200 dark:border-neutral-700">{tag}</span>
                                                {/each}
                                            </span>
                                        {/if}
                                        
                                        {#if notification.status === 'read'}
                                            <span class="text-xs text-green-600 dark:text-green-400">
                                                Read
                                            </span>
                                        {/if}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>
</div>
