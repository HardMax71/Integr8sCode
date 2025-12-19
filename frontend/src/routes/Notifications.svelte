<script>
    import { onMount } from 'svelte';
    import { navigate } from 'svelte-routing';
    import { isAuthenticated, verifyAuth } from '../stores/auth';
    import { addToast } from '../stores/toastStore';
    import { notificationStore, notifications, unreadCount } from '../stores/notificationStore';
    import { get } from 'svelte/store';
    import { fly } from 'svelte/transition';
    import Spinner from '../components/Spinner.svelte';
    
    let loading = false;
    let deleting = {};
    let includeTagsInput = '';
    let excludeTagsInput = '';
    let prefixInput = '';
    
    const bellIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>`;
    const trashIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
    const clockIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    
    
    onMount(async () => {
        // Check cached auth state first
        const currentAuthState = get(isAuthenticated);
        
        if (currentAuthState === false) {
            navigate('/login');
            return;
        }
        
        // Load data immediately using shared store
        loading = true;
        await notificationStore.load(100);
        loading = false;
        
        // Verify auth in background
        verifyAuth().then(isValid => {
            if (!isValid) {
                navigate('/login');
            }
        }).catch(err => {
            console.error('Auth verification failed:', err);
            if (!get(isAuthenticated)) {
                navigate('/login');
            }
        });
    });
    
    async function deleteNotification(id) {
        if (deleting[id]) return;
        
        deleting[id] = true;
        const success = await notificationStore.delete(id);
        if (success) {
            addToast('Notification deleted', 'success');
        } else {
            addToast('Failed to delete notification', 'error');
        }
        deleting[id] = false;
    }
    
    async function markAsRead(notification) {
        if (notification.status === 'read') return;
        await notificationStore.markAsRead(notification.notification_id);
    }
    
    async function markAllAsRead() {
        const success = await notificationStore.markAllAsRead();
        if (success) {
            addToast('All notifications marked as read', 'success');
        } else {
            addToast('Failed to mark all as read', 'error');
        }
    }

    function parseTags(input) {
        return input
            .split(/[\s,]+/)
            .map(s => s.trim())
            .filter(Boolean);
    }

    async function applyFilters() {
        loading = true;
        const include_tags = parseTags(includeTagsInput);
        const exclude_tags = parseTags(excludeTagsInput);
        const tag_prefix = prefixInput.trim() || undefined;
        await notificationStore.load(100, { include_tags, exclude_tags, tag_prefix });
        loading = false;
    }
    
    function formatTimestamp(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
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
    const severityColors = {
        low: 'text-gray-600 dark:text-gray-400',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400'
    };

    function getNotificationIcon(tags = []) {
        const set = new Set(tags || []);
        const check = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
        const warn = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
        const clock = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
        const info = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M12 2a10 10 0 100 20 10 10 0 000-20z" /></svg>`;
        if (set.has('failed') || set.has('error') || set.has('security')) return warn;
        if (set.has('timeout') || set.has('warning')) return clock;
        if (set.has('completed') || set.has('success')) return check;
        return info;
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
                    <button class="btn btn-primary w-full" on:click={applyFilters}>Filter</button>
                </div>
            </div>
        </div>
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">Notifications</h1>
            {#if $notifications.length > 0 && $unreadCount > 0}
                <button
                    on:click={markAllAsRead}
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
        {:else if $notifications.length === 0}
            <div class="card">
                <div class="p-12 text-center">
                    <div class="w-20 h-20 mx-auto mb-4 text-fg-subtle dark:text-dark-fg-subtle">
                        {@html bellIcon}
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
                {#each $notifications as notification (notification.notification_id)}
                    <div
                        in:fly={{ y: 20, duration: 300 }}
                        class="card transition-all duration-200 cursor-pointer {notification.status !== 'read' ? 'bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800/50' : ''}"
                        on:click={() => markAsRead(notification)}
                        on:keydown={(e) => e.key === 'Enter' && markAsRead(notification)}
                        role="button"
                        tabindex="0"
                        aria-label="Mark notification as read"
                    >
                        <div class="p-4">
                            <div class="flex items-start gap-4">
                                <div class="mt-1 {severityColors[notification.severity || 'medium']}">
                                    {@html getNotificationIcon(notification.tags)}
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
                                        
                                        <button
                                            on:click|stopPropagation={() => deleteNotification(notification.notification_id)}
                                            class="btn btn-ghost btn-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 ml-4"
                                            disabled={deleting[notification.notification_id]}
                                        >
                                            {#if deleting[notification.notification_id]}
                                                <Spinner size="small" />
                                            {:else}
                                                {@html trashIcon}
                                            {/if}
                                        </button>
                                        {#if (notification.tags || []).some(t => t.startsWith('exec:'))}
                                            {@const execTag = (notification.tags || []).find(t => t.startsWith('exec:'))}
                                            {#if execTag}
                                                <a
                                                    href={`/editor?execution=${execTag.split(':')[1]}`}
                                                    class="btn btn-ghost btn-sm text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 ml-2"
                                                    on:click|stopPropagation
                                                >
                                                    View result
                                                </a>
                                            {/if}
                                        {/if}
                                    </div>
                                    
                                    <div class="flex items-center gap-4 mt-3">
                                        <span class="inline-flex items-center gap-1 text-xs text-fg-subtle dark:text-dark-fg-subtle">
                                            {@html clockIcon}
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

<style>
    /* Ensure dropdown is above other content */
    .relative {
        z-index: 40;
    }
</style>
