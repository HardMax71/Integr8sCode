<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { fade, fly } from 'svelte/transition';
    import { isAuthenticated, username, userId } from '../stores/auth';
    import { get } from 'svelte/store';
    import { goto } from '@mateothegreat/svelte5-router';
    import { notificationStore, notifications, unreadCount, loading } from '../stores/notificationStore';
    import type { NotificationResponse } from '../lib/api';

    let showDropdown = $state(false);
    // EventSource and reconnect state - not displayed in template, no $state needed
    let eventSource: EventSource | null = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 3;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let hasLoadedInitialData = false;
    
    const bellIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>`;
    const errorIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    const warningIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>`;
    const checkCircleIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    const infoIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M12 2a10 10 0 100 20 10 10 0 000-20z"></path></svg>`;

    function getNotificationIcon(tags: string[] = []): string {
        const set = new Set(tags || []);
        if (set.has('failed') || set.has('error') || set.has('security')) return errorIcon;
        if (set.has('timeout') || set.has('warning')) return warningIcon;
        if (set.has('completed') || set.has('success')) return checkCircleIcon;
        return infoIcon;
    }
    
    const priorityColors = {
        low: 'text-fg-muted dark:text-dark-fg-muted',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400'
    };
    
    onMount(async () => {
        // Subscribe to authentication changes
        const unsubscribe = isAuthenticated.subscribe(async ($isAuth) => {
            if ($isAuth && !hasLoadedInitialData) {
                hasLoadedInitialData = true;
                // Load notifications using the shared store
                await notificationStore.load(20);
                connectToNotificationStream();
            } else if (!$isAuth) {
                // Close stream if not authenticated
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
                hasLoadedInitialData = false;
                notificationStore.clear();
            }
        });
        
        return unsubscribe;
    });
    
    onDestroy(() => {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        clearTimeout(reconnectTimeout);
    });
    
    
    function connectToNotificationStream(): void {
        const isAuth = get(isAuthenticated);
        if (!isAuth) return;
        
        // Check if we've exceeded max attempts
        if (reconnectAttempts >= maxReconnectAttempts) {
            console.error('Max reconnection attempts reached for notification stream');
            return;
        }
        
        // Close existing connection if any
        if (eventSource) {
            eventSource.close();
        }
        
        const url = `/api/v1/events/notifications/stream`;
        eventSource = new EventSource(url, {
            withCredentials: true
        });
        
        eventSource.onopen = (event) => {
            console.log('Notification stream connected', event.type);
            reconnectAttempts = 0; // Reset on successful connection
        };
        
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                
                // Ignore heartbeat and connection messages
                if (data.event === 'heartbeat' || data.event === 'connected') {
                    return;
                }
                
                // Only process actual notification events
                if (data.notification_id && data.subject && data.body) {
                    // Add to shared notification store
                    notificationStore.add(data);
                    
                    // Show browser notification if permission granted
                    if (Notification.permission === 'granted') {
                        new Notification(data.subject, {
                            body: data.body,
                            icon: '/favicon.png'
                        });
                    }
                } else {
                    console.debug('SSE event received but not a notification:', data);
                }
            } catch (err) {
                console.error('Error processing notification:', err);
            }
        };
        
        eventSource.onerror = (error) => {
            // SSE connections will fire error event when closing, ignore if we're not authenticated
            const isAuth = get(isAuthenticated);
            if (!isAuth) {
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
                return;
            }
            
            // Only log actual errors, not normal closure
            if (eventSource && eventSource.readyState !== EventSource.CLOSED) {
                console.error('Notification stream error:', error.type);
            }
            
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            
            // Only reconnect if authenticated and under limit
            if (isAuth && reconnectAttempts < maxReconnectAttempts) {
                reconnectAttempts++;
                console.log(`Reconnecting notification stream... (attempt ${reconnectAttempts}/${maxReconnectAttempts})`);
                
                // Exponential backoff: 5s, 10s, 20s
                const delay = Math.min(5000 * Math.pow(2, reconnectAttempts - 1), 20000);
                
                clearTimeout(reconnectTimeout);
                reconnectTimeout = setTimeout(() => {
                    const stillAuth = get(isAuthenticated);
                    if (stillAuth && !eventSource) {
                        connectToNotificationStream();
                    }
                }, delay);
            } else if (reconnectAttempts >= maxReconnectAttempts) {
                console.error('Max reconnection attempts reached for notification stream');
            }
        };
    }
    
    async function markAsRead(notification: NotificationResponse): Promise<void> {
        if (notification.status === 'read') return;
        await notificationStore.markAsRead(notification.notification_id);
    }
    
    async function markAllAsRead(): Promise<void> {
        const success = await notificationStore.markAllAsRead();
        if (success) {
            // Close dropdown after marking all as read
            showDropdown = false;
        }
    }

    function toggleDropdown(): void {
        showDropdown = !showDropdown;

        if (showDropdown && $unreadCount > 0) {
            // Mark visible notifications as read after a delay
            setTimeout(() => {
                $notifications.slice(0, 5).forEach(n => {
                    if (n.status !== 'read') {
                        markAsRead(n);
                    }
                });
            }, 2000);
        }
    }

    function formatTime(timestamp: string): string {
        // Backend sends ISO datetime strings
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now.getTime() - date.getTime();

        if (diff < 60000) return 'just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return date.toLocaleDateString();
    }
    
    // getNotificationIcon now based on tags above

    // Track permission state reactively
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
        {@html bellIcon}
        {#if $unreadCount > 0}
            <span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center">
                {$unreadCount > 9 ? '9+' : $unreadCount}
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
                    {#if $unreadCount > 0}
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
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path>
                        </svg>
                        Enable desktop notifications
                    </button>
                {/if}
            </div>
            
            <div class="max-h-96 overflow-y-auto">
                {#if $loading}
                    <div class="p-8 text-center">
                        <span class="loading loading-spinner loading-sm"></span>
                    </div>
                {:else if $notifications.length === 0}
                    <div class="p-8 text-center text-fg-muted dark:text-dark-fg-muted">
                        No notifications yet
                    </div>
                {:else}
                    {#each $notifications as notification}
                        <div
                            class="p-4 border-b border-border-default/50 dark:border-dark-border-default hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover cursor-pointer transition-colors"
                            class:bg-blue-50={notification.status !== 'read'}
                            class:dark:bg-blue-900={notification.status !== 'read'}
                            onclick={() => {
                                markAsRead(notification);
                                if (notification.action_url) {
                                    // Use goto for internal links, window.location for external
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
                                    {@html getNotificationIcon(notification.tags)}
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
