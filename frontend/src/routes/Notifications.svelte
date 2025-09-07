<script>
    import { onMount } from 'svelte';
    import { navigate } from 'svelte-routing';
    import { api } from '../lib/api';
    import { isAuthenticated, verifyAuth } from '../stores/auth';
    import { addNotification } from '../stores/notifications';
    import { notificationStore, notifications, unreadCount } from '../stores/notificationStore';
    import { get } from 'svelte/store';
    import { fly } from 'svelte/transition';
    import Spinner from '../components/Spinner.svelte';
    
    let loading = false;
    let deleting = {};
    
    const bellIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>`;
    const trashIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
    const clockIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    
    const notificationIcons = {
        execution_completed: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        execution_failed: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        execution_timeout: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        system_update: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>`,
        security_alert: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>`,
        resource_limit: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"></path></svg>`,
        account_update: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>`,
        settings_changed: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>`
    };
    
    const priorityColors = {
        low: 'text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30',
        medium: 'text-yellow-600 dark:text-yellow-400 bg-yellow-100 dark:bg-yellow-900/30',
        high: 'text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30'
    };
    
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
            addNotification('Notification deleted', 'success');
        } else {
            addNotification('Failed to delete notification', 'error');
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
            addNotification('All notifications marked as read', 'success');
        } else {
            addNotification('Failed to mark all as read', 'error');
        }
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
    
    function getNotificationIcon(type) {
        return notificationIcons[type] || bellIcon;
    }
    
    function getNotificationColor(type) {
        const colorMap = {
            execution_completed: 'text-green-600 dark:text-green-400',
            execution_failed: 'text-red-600 dark:text-red-400',
            execution_timeout: 'text-yellow-600 dark:text-yellow-400',
            system_update: 'text-blue-600 dark:text-blue-400',
            security_alert: 'text-red-600 dark:text-red-400',
            resource_limit: 'text-orange-600 dark:text-orange-400',
            account_update: 'text-purple-600 dark:text-purple-400',
            settings_changed: 'text-gray-600 dark:text-gray-400'
        };
        return colorMap[type] || 'text-gray-600 dark:text-gray-400';
    }
</script>

<div class="min-h-screen bg-bg-default dark:bg-dark-bg-default">
    <div class="container mx-auto px-4 py-8 max-w-5xl">
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
                                <div class="{getNotificationColor(notification.notification_type || 'default')} mt-1">
                                    {@html getNotificationIcon(notification.notification_type || 'default')}
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
                                            class="btn btn-ghost btn-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900 dark:hover:bg-opacity-20 ml-4"
                                            disabled={deleting[notification.notification_id]}
                                        >
                                            {#if deleting[notification.notification_id]}
                                                <Spinner size="small" />
                                            {:else}
                                                {@html trashIcon}
                                            {/if}
                                        </button>
                                    </div>
                                    
                                    <div class="flex items-center gap-4 mt-3">
                                        <span class="inline-flex items-center gap-1 text-xs text-fg-subtle dark:text-dark-fg-subtle">
                                            {@html clockIcon}
                                            {formatTimestamp(notification.created_at)}
                                        </span>
                                        
                                        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-neutral-100 dark:bg-neutral-800 text-fg-muted dark:text-dark-fg-muted">
                                            {notification.channel}
                                        </span>
                                        
                                        {#if notification.priority}
                                            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {priorityColors[notification.priority] || priorityColors.medium}">
                                                {notification.priority}
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