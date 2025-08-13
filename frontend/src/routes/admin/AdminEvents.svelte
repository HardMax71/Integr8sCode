<script>
    import { onMount, onDestroy } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let events = [];
    let loading = false;
    let totalEvents = 0;
    let currentPage = 1;
    let pageSize = 10;
    let selectedEvent = null;
    let showFilters = false;
    let stats = null;
    let refreshInterval = null;
    let activeReplaySession = null;
    let replayCheckInterval = null;
    
    // Filters
    let filters = {
        event_types: [],
        aggregate_id: '',
        correlation_id: '',
        user_id: '',
        service_name: '',
        search_text: '',
        start_time: '',
        end_time: ''
    };
    
    // Event type options
    const eventTypes = [
        'execution.requested',
        'execution.started',
        'execution.completed',
        'execution.failed',
        'execution.timeout',
        'pod.created',
        'pod.running',
        'pod.succeeded',
        'pod.failed',
        'pod.terminated'
    ];
    
    $: totalPages = Math.ceil(totalEvents / pageSize);
    $: skip = (currentPage - 1) * pageSize;
    
    onMount(() => {
        loadEvents();
        loadStats();
        // Auto-refresh every 30 seconds
        refreshInterval = setInterval(() => {
            loadEvents();
            loadStats();
        }, 30000);
    });
    
    onDestroy(() => {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
        if (replayCheckInterval) {
            clearInterval(replayCheckInterval);
        }
    });
    
    async function loadEvents() {
        loading = true;
        try {
            const response = await api.post('/api/v1/admin/events/browse', {
                filters: {
                    ...filters,
                    start_time: filters.start_time ? new Date(filters.start_time).toISOString() : null,
                    end_time: filters.end_time ? new Date(filters.end_time).toISOString() : null
                },
                skip,
                limit: pageSize,
                sort_by: 'timestamp',
                sort_order: -1
            });
            
            // Ensure events is always an array
            events = response?.events || [];
            totalEvents = response?.total || 0;
        } catch (error) {
            console.error('Failed to load events:', error);
            addNotification(`Failed to load events: ${error.message}`, 'error');
            events = [];
            totalEvents = 0;
        } finally {
            loading = false;
        }
    }
    
    async function loadStats() {
        try {
            stats = await api.get('/api/v1/admin/events/stats?hours=24');
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    }
    
    async function loadEventDetail(eventId) {
        try {
            const response = await api.get(`/api/v1/admin/events/${eventId}`);
            selectedEvent = response;
        } catch (error) {
            addNotification(`Failed to load event detail: ${error.message}`, 'error');
        }
    }
    
    async function checkReplayStatus(sessionId) {
        try {
            const status = await api.get(`/api/v1/admin/events/replay/${sessionId}/status`);
            activeReplaySession = status;
            
            // If replay is complete, stop checking
            if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
                if (replayCheckInterval) {
                    clearInterval(replayCheckInterval);
                    replayCheckInterval = null;
                }
                
                // Show completion notification
                if (status.status === 'completed') {
                    addNotification(
                        `Replay completed! Processed ${status.replayed_events} events successfully.`, 
                        'success'
                    );
                } else if (status.status === 'failed') {
                    addNotification(
                        `Replay failed: ${status.error || 'Unknown error'}`, 
                        'error'
                    );
                }
                
                // Clear active session after a delay
                setTimeout(() => {
                    activeReplaySession = null;
                }, 5000);
            }
        } catch (error) {
            console.error('Failed to check replay status:', error);
            // Stop checking on error
            if (replayCheckInterval) {
                clearInterval(replayCheckInterval);
                replayCheckInterval = null;
            }
        }
    }

    async function replayEvent(eventId, dryRun = true) {
        try {
            // For actual replay, confirm with user
            if (!dryRun && !confirm('Are you sure you want to replay this event? This will re-process the event through the system.')) {
                return;
            }
            
            const response = await api.post('/api/v1/admin/events/replay', {
                event_ids: [eventId],
                dry_run: dryRun
            });
            
            if (dryRun) {
                // More informative dry run message
                if (response.events_preview && response.events_preview.length > 0) {
                    const event = response.events_preview[0];
                    addNotification(
                        `Dry run: Would replay "${event.event_type}" event from ${new Date(event.timestamp).toLocaleString()}. Click on the event row to see details and perform actual replay.`, 
                        'info'
                    );
                } else {
                    addNotification(`Dry run: ${response.total_events} events would be replayed`, 'info');
                }
            } else {
                addNotification(`Replay scheduled! Tracking progress...`, 'success');
                
                // Start tracking replay progress
                if (response.session_id) {
                    activeReplaySession = {
                        session_id: response.session_id,
                        status: 'scheduled',
                        total_events: response.total_events,
                        replayed_events: 0,
                        progress_percentage: 0
                    };
                    
                    // Check status immediately
                    checkReplayStatus(response.session_id);
                    
                    // Then check every 2 seconds
                    replayCheckInterval = setInterval(() => {
                        checkReplayStatus(response.session_id);
                    }, 2000);
                }
                
                // Close the modal after successful replay
                selectedEvent = null;
            }
        } catch (error) {
            addNotification(`Failed to replay event: ${error.message}`, 'error');
        }
    }
    
    async function deleteEvent(eventId) {
        if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) {
            return;
        }
        
        try {
            await api.delete(`/api/v1/admin/events/${eventId}`);
            addNotification('Event deleted successfully', 'success');
            await loadEvents();
            selectedEvent = null;
        } catch (error) {
            addNotification(`Failed to delete event: ${error.message}`, 'error');
        }
    }
    
    async function exportEvents() {
        try {
            const params = new URLSearchParams();
            if (filters.event_types.length > 0) {
                params.append('event_types', filters.event_types.join(','));
            }
            if (filters.start_time) {
                params.append('start_time', new Date(filters.start_time).toISOString());
            }
            if (filters.end_time) {
                params.append('end_time', new Date(filters.end_time).toISOString());
            }
            
            window.open(`/api/v1/admin/events/export/csv?${params.toString()}`, '_blank');
        } catch (error) {
            addNotification(`Failed to export events: ${error.message}`, 'error');
        }
    }
    
    function formatTimestamp(timestamp) {
        // Backend sends Unix timestamps in seconds, JS Date expects milliseconds
        return new Date(timestamp * 1000).toLocaleString();
    }
    
    function formatDuration(seconds) {
        if (!seconds) return '-';
        return `${seconds.toFixed(2)}s`;
    }
    
    function getEventTypeColor(eventType) {
        if (eventType.includes('.completed') || eventType.includes('.succeeded')) return 'text-green-600';
        if (eventType.includes('.failed') || eventType.includes('.timeout')) return 'text-red-600';
        if (eventType.includes('.started') || eventType.includes('.running')) return 'text-blue-600';
        return 'text-gray-600';
    }
    
    function clearFilters() {
        filters = {
            event_types: [],
            aggregate_id: '',
            correlation_id: '',
            user_id: '',
            service_name: '',
            search_text: '',
            start_time: '',
            end_time: ''
        };
        currentPage = 1;
        loadEvents();
    }
</script>

<AdminLayout path="/admin/events">
    <div class="container mx-auto px-4 pb-8">
        <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold">Event Browser</h1>
            
            <div class="flex flex-wrap gap-2">
                <button
                    on:click={() => showFilters = !showFilters}
                    class="btn btn-sm sm:btn-md flex items-center gap-1 sm:gap-2 transition-all duration-200"
                    class:btn-primary={showFilters}
                    class:btn-secondary-outline={!showFilters}
                    class:ring-2={showFilters}
                    class:ring-primary={showFilters}
                    class:ring-offset-2={showFilters}
                    class:dark:ring-offset-dark-bg-default={showFilters}
                >
                    <svg class="w-4 h-4 transition-transform duration-200" class:rotate-180={showFilters} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                    </svg>
                    <span class="hidden sm:inline">Filters</span>
                    {#if filters.event_types.length > 0 || filters.search_text}
                        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {showFilters ? 'bg-white text-primary' : 'bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary-light'}">
                            {filters.event_types.length || 1}
                        </span>
                    {/if}
                </button>
                
                <button
                    on:click={exportEvents}
                    class="btn btn-sm sm:btn-md btn-secondary-outline flex items-center gap-1 sm:gap-2"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
                    </svg>
                    <span class="hidden sm:inline">Export CSV</span>
                </button>
                
                <button
                    on:click={loadEvents}
                    class="btn btn-sm sm:btn-md btn-primary flex items-center gap-1 sm:gap-2"
                    disabled={loading}
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" class:animate-spin={loading}>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    <span class="hidden sm:inline">Refresh</span>
                </button>
            </div>
        </div>
        
        {#if activeReplaySession}
            <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
                <div class="flex items-center justify-between mb-2">
                    <h3 class="font-semibold text-blue-900 dark:text-blue-100">Replay in Progress</h3>
                    <span class="text-sm text-blue-700 dark:text-blue-300">
                        {activeReplaySession.status}
                    </span>
                </div>
                <div class="mb-2">
                    <div class="flex justify-between text-sm text-blue-700 dark:text-blue-300 mb-1">
                        <span>Progress: {activeReplaySession.replayed_events} / {activeReplaySession.total_events} events</span>
                        <span>{activeReplaySession.progress_percentage}%</span>
                    </div>
                    <div class="w-full bg-blue-200 dark:bg-blue-800 rounded-full h-2">
                        <div 
                            class="bg-blue-600 dark:bg-blue-400 h-2 rounded-full transition-all duration-300"
                            style="width: {activeReplaySession.progress_percentage}%"
                        ></div>
                    </div>
                </div>
                {#if activeReplaySession.failed_events > 0}
                    <div class="text-sm text-red-600 dark:text-red-400 mt-2">
                        Failed: {activeReplaySession.failed_events} events
                    </div>
                {/if}
            </div>
        {/if}
        
        {#if stats}
            <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
                <div class="card p-4">
                    <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Events (Last 24h)</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{stats?.total_events?.toLocaleString() || '0'}</div>
                    <div class="text-xs text-fg-muted dark:text-dark-fg-muted">of {totalEvents?.toLocaleString() || '0'} total</div>
                </div>
                
                <div class="card p-4">
                    <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Error Rate (24h)</div>
                    <div class="text-2xl font-bold {stats?.error_rate > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}">{stats?.error_rate || 0}%</div>
                </div>
                
                <div class="card p-4">
                    <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Avg Execution Time (24h)</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{stats?.avg_processing_time ? stats.avg_processing_time.toFixed(2) : '0'}s</div>
                </div>
                
                <div class="card p-4">
                    <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Active Users (24h)</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{stats?.top_users?.length || 0}</div>
                    <div class="text-xs text-fg-muted dark:text-dark-fg-muted">with events</div>
                </div>
            </div>
        {/if}
        
        {#if showFilters}
            <div class="card mb-6">
                <div class="p-6">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Filters</h3>
                    
                    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Event Types</span>
                            </label>
                            <select
                                bind:value={filters.event_types}
                                multiple
                                class="form-select-standard h-32"
                            >
                                {#each eventTypes as type}
                                    <option value={type}>{type}</option>
                                {/each}
                            </select>
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Search Text</span>
                            </label>
                            <input
                                type="text"
                                bind:value={filters.search_text}
                                placeholder="Search in events..."
                                class="form-input-standard"
                            />
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Correlation ID</span>
                            </label>
                            <input
                                type="text"
                                bind:value={filters.correlation_id}
                                placeholder="req_abc123..."
                                class="form-input-standard"
                            />
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Aggregate ID</span>
                            </label>
                            <input
                                type="text"
                                bind:value={filters.aggregate_id}
                                placeholder="execution_id..."
                                class="form-input-standard"
                            />
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">User ID</span>
                            </label>
                            <input
                                type="text"
                                bind:value={filters.user_id}
                                placeholder="user_123..."
                                class="form-input-standard"
                            />
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Service Name</span>
                            </label>
                            <input
                                type="text"
                                bind:value={filters.service_name}
                                placeholder="execution-service..."
                                class="form-input-standard"
                            />
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Start Time</span>
                            </label>
                            <input
                                type="datetime-local"
                                bind:value={filters.start_time}
                                class="form-input-standard"
                            />
                        </div>
                        
                        <div class="form-control">
                            <label class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">End Time</span>
                            </label>
                            <input
                                type="datetime-local"
                                bind:value={filters.end_time}
                                class="form-input-standard"
                            />
                        </div>
                    </div>
                    
                    <div class="flex justify-end gap-3 mt-4">
                        <button
                            on:click={clearFilters}
                            class="btn btn-ghost"
                        >
                            Clear
                        </button>
                        <button
                            on:click={() => { currentPage = 1; loadEvents(); }}
                            class="btn btn-primary"
                        >
                            Apply Filters
                        </button>
                    </div>
                </div>
            </div>
        {/if}
        
        <div class="card">
            <div class="p-6">
                <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-4">
                    <div class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                        <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default">
                            Events ({totalEvents?.toLocaleString() || '0'} total)
                        </h3>
                        <div class="flex items-center gap-2">
                            <span class="text-sm text-fg-muted dark:text-dark-fg-muted">Show:</span>
                            <select
                                bind:value={pageSize}
                                on:change={() => { currentPage = 1; loadEvents(); }}
                                class="form-select-standard text-sm py-1"
                            >
                                <option value={10}>10</option>
                                <option value={25}>25</option>
                                <option value={50}>50</option>
                                <option value={100}>100</option>
                            </select>
                            <span class="text-sm text-fg-muted dark:text-dark-fg-muted hidden sm:inline">per page</span>
                        </div>
                    </div>
                    
                    {#if totalPages > 1}
                    <div class="flex flex-col gap-2">
                        <div class="flex items-center gap-1 sm:gap-2 flex-wrap justify-center sm:justify-end">
                            <button
                                class="btn btn-sm btn-secondary-outline"
                                disabled={currentPage === 1}
                                on:click={() => { currentPage = 1; loadEvents(); }}
                                title="First page"
                            >
                                ««
                            </button>
                            <button
                                class="btn btn-sm btn-secondary-outline"
                                disabled={currentPage === 1}
                                on:click={() => { currentPage--; loadEvents(); }}
                                title="Previous page"
                            >
                                «
                            </button>
                            
                            <div class="flex items-center gap-1">
                                {#if totalPages <= 3}
                                    {#each Array(totalPages) as _, i}
                                        <button
                                            class="btn btn-sm {currentPage === i + 1 ? 'btn-primary' : 'btn-secondary-outline'}"
                                            on:click={() => { currentPage = i + 1; loadEvents(); }}
                                        >
                                            {i + 1}
                                        </button>
                                    {/each}
                                {:else}
                                    {#if currentPage > 2}
                                        <button
                                            class="btn btn-sm btn-secondary-outline"
                                            on:click={() => { currentPage = 1; loadEvents(); }}
                                        >
                                            1
                                        </button>
                                        <span class="px-1 text-fg-muted dark:text-dark-fg-muted">...</span>
                                    {/if}
                                    
                                    {#each Array(3) as _, i}
                                        {#if currentPage - 1 + i > 0 && currentPage - 1 + i <= totalPages}
                                            <button
                                                class="btn btn-sm {currentPage === currentPage - 1 + i ? 'btn-primary' : 'btn-secondary-outline'}"
                                                on:click={() => { currentPage = currentPage - 1 + i; loadEvents(); }}
                                            >
                                                {currentPage - 1 + i}
                                            </button>
                                        {/if}
                                    {/each}
                                    
                                    {#if currentPage < totalPages - 1}
                                        <span class="px-1 text-fg-muted dark:text-dark-fg-muted">...</span>
                                        <button
                                            class="btn btn-sm btn-secondary-outline"
                                            on:click={() => { currentPage = totalPages; loadEvents(); }}
                                        >
                                            {totalPages}
                                        </button>
                                    {/if}
                                {/if}
                            </div>
                            
                            <button
                                class="btn btn-sm btn-secondary-outline"
                                disabled={currentPage === totalPages}
                                on:click={() => { currentPage++; loadEvents(); }}
                                title="Next page"
                            >
                                »
                            </button>
                            <button
                                class="btn btn-sm btn-secondary-outline"
                                disabled={currentPage === totalPages}
                                on:click={() => { currentPage = totalPages; loadEvents(); }}
                                title="Last page"
                            >
                                »»
                            </button>
                        </div>
                        
                        <div class="text-center sm:text-right">
                            <span class="text-sm text-fg-muted dark:text-dark-fg-muted">
                                Page {currentPage} of {totalPages}
                            </span>
                        </div>
                    </div>
                    {/if}
                </div>
                
                <!-- Desktop view - Table -->
                <div class="hidden lg:block overflow-x-auto">
                    <table class="w-full divide-y divide-border-default dark:divide-dark-border-default">
                        <thead class="bg-neutral-50 dark:bg-neutral-900">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Timestamp</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Event Type</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider hidden xl:table-cell">Correlation ID</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">User</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider hidden xl:table-cell">Service</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each events || [] as event}
                                <tr
                                    class="hover:bg-neutral-50 dark:hover:bg-neutral-800 cursor-pointer transition-colors"
                                    on:click={() => loadEventDetail(event.event_id)}
                                >
                                    <td class="px-4 py-3 text-sm text-fg-default dark:text-dark-fg-default">
                                        <div class="flex items-center gap-1">
                                            <svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                            </svg>
                                            <span class="truncate max-w-[150px]" title={formatTimestamp(event.timestamp)}>
                                                {formatTimestamp(event.timestamp)}
                                            </span>
                                        </div>
                                    </td>
                                    <td class="px-4 py-3 text-sm text-fg-default dark:text-dark-fg-default">
                                        <span class={`${getEventTypeColor(event.event_type)} truncate block max-w-[200px]`} title={event.event_type}>
                                            {event.event_type}
                                        </span>
                                    </td>
                                    <td class="px-4 py-3 font-mono text-sm text-fg-default dark:text-dark-fg-default hidden xl:table-cell">
                                        <span class="truncate block max-w-[150px]" title={event.correlation_id}>
                                            {event.correlation_id}
                                        </span>
                                    </td>
                                    <td class="px-4 py-3 text-sm text-fg-default dark:text-dark-fg-default">
                                        <span class="truncate block max-w-[100px]" title={event.metadata?.user_id || '-'}>
                                            {event.metadata?.user_id || '-'}
                                        </span>
                                    </td>
                                    <td class="px-4 py-3 text-sm text-fg-default dark:text-dark-fg-default hidden xl:table-cell">
                                        <span class="truncate block max-w-[150px]" title={event.metadata?.service_name || '-'}>
                                            {event.metadata?.service_name || '-'}
                                        </span>
                                    </td>
                                    <td class="px-4 py-3 text-sm text-fg-default dark:text-dark-fg-default">
                                        <div class="flex gap-1">
                                            <button
                                                on:click|stopPropagation={() => replayEvent(event.event_id)}
                                                class="btn btn-ghost btn-xs p-1"
                                                title="Preview replay (dry run)"
                                            >
                                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                                </svg>
                                            </button>
                                            <button
                                                on:click|stopPropagation={() => replayEvent(event.event_id, false)}
                                                class="btn btn-ghost btn-xs p-1 text-blue-600 dark:text-blue-400"
                                                title="Replay event"
                                            >
                                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                                </svg>
                                            </button>
                                            <button
                                                on:click|stopPropagation={() => deleteEvent(event.event_id)}
                                                class="btn btn-ghost btn-xs p-1 text-red-600 dark:text-red-400"
                                                title="Delete event"
                                            >
                                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                </svg>
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>

                <!-- Mobile/Tablet view - Cards -->
                <div class="lg:hidden space-y-3">
                    {#each events || [] as event}
                        <div 
                            class="bg-bg-alt dark:bg-dark-bg-alt rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
                            on:click={() => loadEventDetail(event.event_id)}
                        >
                            <div class="flex justify-between items-start mb-2">
                                <div class="flex-1 min-w-0">
                                    <div class={`font-medium ${getEventTypeColor(event.event_type)} truncate`}>
                                        {event.event_type}
                                    </div>
                                    <div class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">
                                        {formatTimestamp(event.timestamp)}
                                    </div>
                                </div>
                                <div class="flex gap-1 ml-2">
                                    <button
                                        on:click|stopPropagation={() => replayEvent(event.event_id)}
                                        class="btn btn-ghost btn-xs p-1"
                                        title="Preview replay"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                        </svg>
                                    </button>
                                    <button
                                        on:click|stopPropagation={() => replayEvent(event.event_id, false)}
                                        class="btn btn-ghost btn-xs p-1 text-blue-600 dark:text-blue-400"
                                        title="Replay"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                        </svg>
                                    </button>
                                    <button
                                        on:click|stopPropagation={() => deleteEvent(event.event_id)}
                                        class="btn btn-ghost btn-xs p-1 text-red-600 dark:text-red-400"
                                        title="Delete"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                    </button>
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-2 text-sm">
                                <div>
                                    <span class="text-fg-muted dark:text-dark-fg-muted">User:</span>
                                    <span class="ml-1 font-mono">{event.metadata?.user_id || '-'}</span>
                                </div>
                                <div>
                                    <span class="text-fg-muted dark:text-dark-fg-muted">Service:</span>
                                    <span class="ml-1 truncate inline-block max-w-[120px] align-bottom" title={event.metadata?.service_name || '-'}>
                                        {event.metadata?.service_name || '-'}
                                    </span>
                                </div>
                                <div class="col-span-2">
                                    <span class="text-fg-muted dark:text-dark-fg-muted">Correlation:</span>
                                    <span class="ml-1 font-mono text-xs truncate inline-block max-w-[200px] align-bottom" title={event.correlation_id}>
                                        {event.correlation_id}
                                    </span>
                                </div>
                            </div>
                        </div>
                    {/each}
                </div>
                    
                    {#if events.length === 0}
                        <div class="text-center py-8 text-fg-muted dark:text-dark-fg-muted">
                            No events found
                        </div>
                    {/if}
            </div>
        </div>
    </div>

    {#if selectedEvent}
        <div class="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:p-0">
            <div class="fixed inset-0 bg-black bg-opacity-50" on:click={() => selectedEvent = null}></div>
            <div class="relative inline-block align-bottom bg-bg-alt dark:bg-dark-bg-alt rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-4xl sm:w-full p-6">
                <h3 class="font-bold text-lg mb-4">Event Details</h3>
                
                <div class="space-y-4">
                    <div>
                        <h4 class="font-semibold mb-2">Basic Information</h4>
                        <table class="w-full">
                            <tbody>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Event ID</td>
                                    <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{selectedEvent.event.event_id}</td>
                                </tr>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Event Type</td>
                                    <td class="px-4 py-2 {getEventTypeColor(selectedEvent.event.event_type)}">
                                        {selectedEvent.event.event_type}
                                    </td>
                                </tr>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Timestamp</td>
                                    <td class="px-4 py-2 text-sm text-fg-default dark:text-dark-fg-default">{formatTimestamp(selectedEvent.event.timestamp)}</td>
                                </tr>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Correlation ID</td>
                                    <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{selectedEvent.event.correlation_id}</td>
                                </tr>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Aggregate ID</td>
                                    <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{selectedEvent.event.aggregate_id || '-'}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    
                    <div>
                        <h4 class="font-semibold mb-2">Metadata</h4>
                        <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default">
{JSON.stringify(selectedEvent.event.metadata, null, 2)}
                        </pre>
                    </div>
                    
                    <div>
                        <h4 class="font-semibold mb-2">Payload</h4>
                        <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default">
{JSON.stringify(selectedEvent.event.payload, null, 2)}
                        </pre>
                    </div>
                    
                    {#if selectedEvent.related_events && selectedEvent.related_events.length > 0}
                        <div>
                            <h4 class="font-semibold mb-2">Related Events</h4>
                            <div class="space-y-1">
                                {#each selectedEvent.related_events || [] as related}
                                    <button
                                        on:click={() => loadEventDetail(related.event_id)}
                                        class="flex justify-between items-center w-full p-2 bg-neutral-100 dark:bg-neutral-800 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors"
                                    >
                                        <span class={getEventTypeColor(related.event_type)}>
                                            {related.event_type}
                                        </span>
                                        <span class="text-sm text-fg-muted dark:text-dark-fg-muted">
                                            {formatTimestamp(related.timestamp)}
                                        </span>
                                    </button>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>
                
                <div class="mt-5 sm:mt-6 flex gap-3 justify-end">
                    <button
                        on:click={() => replayEvent(selectedEvent.event.event_id, false)}
                        class="btn btn-primary"
                    >
                        Replay Event
                    </button>
                    <button
                        on:click={() => selectedEvent = null}
                        class="btn btn-secondary-outline"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    {/if}
</AdminLayout>