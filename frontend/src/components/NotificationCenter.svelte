<script>
    import { onMount, onDestroy } from 'svelte';
    import { api } from '../lib/api';
    import { fade, fly } from 'svelte/transition';
    import { isAuthenticated, username, userId } from '../stores/auth';
    import { get } from 'svelte/store';
    import { navigate } from 'svelte-routing';
    
    let notifications = [];
    let unreadCount = 0;
    let showDropdown = false;
    let loading = false;
    let eventSource = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 3;
    let reconnectTimeout = null;
    let hasLoadedInitialData = false;
    
    const bellIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>`;
    
    const notificationIcons = {
        execution_completed: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        execution_failed: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`,
        security_alert: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>`,
        system_update: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`
    };
    
    const priorityColors = {
        low: 'text-gray-600 dark:text-gray-400',
        medium: 'text-blue-600 dark:text-blue-400',
        high: 'text-orange-600 dark:text-orange-400',
        urgent: 'text-red-600 dark:text-red-400'
    };
    
    onMount(async () => {
        // Subscribe to authentication changes
        const unsubscribe = isAuthenticated.subscribe(async ($isAuth) => {
            if ($isAuth && !hasLoadedInitialData) {
                hasLoadedInitialData = true;
                // Load data in parallel, not sequentially
                const loadPromises = [
                    loadNotifications(),
                    loadUnreadCount()
                ];
                await Promise.all(loadPromises);
                connectToNotificationStream();
            } else if (!$isAuth) {
                // Close stream if not authenticated
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
                hasLoadedInitialData = false;
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
    
    async function loadNotifications() {
        loading = true;
        try {
            const response = await api.get('/api/v1/notifications?limit=20');
            notifications = response.notifications;
        } catch (error) {
            console.error('Failed to load notifications:', error);
        } finally {
            loading = false;
        }
    }
    
    async function loadUnreadCount() {
        try {
            const response = await api.get('/api/v1/notifications/unread-count');
            unreadCount = response.unread_count;
        } catch (error) {
            console.error('Failed to load unread count:', error);
        }
    }
    
    function connectToNotificationStream() {
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
                const notification = JSON.parse(event.data);
                
                // Add to notifications list
                notifications = [notification, ...notifications].slice(0, 20);
                
                // Increment unread count
                unreadCount++;
                
                // Show browser notification if permission granted
                if (Notification.permission === 'granted') {
                    new Notification(notification.subject, {
                        body: notification.body,
                        icon: '/favicon.png'
                    });
                }
            } catch (error) {
                console.error('Error processing notification:', error);
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
    
    async function markAsRead(notification) {
        if (notification.status === 'read') return;
        
        try {
            await api.put(`/api/v1/notifications/${notification.notification_id}/read`);
            
            // Update local state
            notification.status = 'read';
            notification.read_at = new Date().toISOString();
            notifications = notifications;
            
            // Update unread count
            unreadCount = Math.max(0, unreadCount - 1);
        } catch (error) {
            console.error('Failed to mark notification as read:', error);
        }
    }
    
    async function markAllAsRead() {
        try {
            await api.post('/api/v1/notifications/mark-all-read');
            
            // Update local state
            notifications = notifications.map(n => ({
                ...n,
                status: 'read',
                read_at: new Date().toISOString()
            }));
            
            unreadCount = 0;
        } catch (error) {
            console.error('Failed to mark all as read:', error);
        }
    }
    
    function toggleDropdown() {
        showDropdown = !showDropdown;
        
        if (showDropdown && unreadCount > 0) {
            // Mark visible notifications as read after a delay
            setTimeout(() => {
                notifications.slice(0, 5).forEach(n => {
                    if (n.status !== 'read') {
                        markAsRead(n);
                    }
                });
            }, 2000);
        }
    }
    
    function formatTime(timestamp) {
        // Backend sends Unix timestamps in seconds, JS Date expects milliseconds
        const date = new Date(timestamp * 1000);
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) return 'just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return date.toLocaleDateString();
    }
    
    function getNotificationIcon(type) {
        return notificationIcons[type] || notificationIcons.system_update;
    }
    
    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
</script>

<div class="relative">
    <button
        on:click={toggleDropdown}
        class="btn btn-ghost btn-icon relative"
        aria-label="Notifications"
    >
        {@html bellIcon}
        {#if unreadCount > 0}
            <span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center">
                {unreadCount > 9 ? '9+' : unreadCount}
            </span>
        {/if}
    </button>
    
    {#if showDropdown}
        <div
            class="absolute right-0 mt-2 w-96 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-50"
            transition:fly={{ y: -10, duration: 200 }}
        >
            <div class="p-4 border-b border-gray-200 dark:border-gray-700">
                <div class="flex justify-between items-center">
                    <h3 class="font-semibold text-lg">Notifications</h3>
                    {#if unreadCount > 0}
                        <button
                            on:click={markAllAsRead}
                            class="text-sm text-blue-600 dark:text-blue-400 hover:underline"
                        >
                            Mark all as read
                        </button>
                    {/if}
                </div>
            </div>
            
            <div class="max-h-96 overflow-y-auto">
                {#if loading}
                    <div class="p-8 text-center">
                        <span class="loading loading-spinner loading-sm"></span>
                    </div>
                {:else if notifications.length === 0}
                    <div class="p-8 text-center text-gray-500">
                        No notifications yet
                    </div>
                {:else}
                    {#each notifications as notification}
                        <div
                            class="p-4 border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer transition-colors"
                            class:bg-blue-50={notification.status !== 'read'}
                            class:dark:bg-blue-900={notification.status !== 'read'}
                            on:click={() => {
                                markAsRead(notification);
                                if (notification.action_url) {
                                    window.location.href = notification.action_url;
                                }
                            }}
                        >
                            <div class="flex items-start space-x-3">
                                <div class={`mt-1 ${priorityColors[notification.priority]}`}>
                                    {@html getNotificationIcon(notification.notification_type)}
                                </div>
                                <div class="flex-1 min-w-0">
                                    <p class="font-medium text-sm">
                                        {notification.subject}
                                    </p>
                                    <p class="text-sm text-gray-600 dark:text-gray-400 mt-1">
                                        {notification.body}
                                    </p>
                                    <p class="text-xs text-gray-500 dark:text-gray-500 mt-2">
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
            
            <div class="p-3 border-t border-gray-200 dark:border-gray-700">
                <button
                    on:click={() => {
                        showDropdown = false;
                        navigate('/notifications');
                    }}
                    class="block w-full text-center text-sm text-blue-600 dark:text-blue-400 hover:underline bg-transparent border-none cursor-pointer"
                >
                    View all notifications
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    /* Ensure dropdown is above other content */
    .relative {
        z-index: 40;
    }
</style>