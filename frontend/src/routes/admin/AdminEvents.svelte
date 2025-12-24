<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import {
        browseEventsApiV1AdminEventsBrowsePost,
        getEventStatsApiV1AdminEventsStatsGet,
        getEventDetailApiV1AdminEventsEventIdGet,
        getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
        replayEventsApiV1AdminEventsReplayPost,
        deleteEventApiV1AdminEventsEventIdDelete,
        getUserOverviewApiV1AdminUsersUserIdOverviewGet,
        type EventResponse,
        type EventStatsResponse,
        type EventDetailResponse,
        type EventReplayStatusResponse,
        type AdminUserOverview,
    } from '../../lib/api';
    import { unwrap, unwrapOr } from '../../lib/api-interceptors';
    import { addToast } from '../../stores/toastStore';
    import { formatTimestamp } from '../../lib/formatters';
    import AdminLayout from './AdminLayout.svelte';
    import Spinner from '../../components/Spinner.svelte';
    import Modal from '../../components/Modal.svelte';
    import EventTypeIcon from '../../components/EventTypeIcon.svelte';
    import {
        Filter, Download, RefreshCw, X, Eye, Play, Trash2,
        ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight,
        FileText, Code, AlertTriangle
    } from '@lucide/svelte';

    let events = $state<EventResponse[]>([]);
    let loading = $state(false);
    let totalEvents = $state(0);
    let currentPage = $state(1);
    let pageSize = $state(10);
    let selectedEvent = $state<EventDetailResponse | null>(null);
    let showFilters = $state(false);
    let stats = $state<EventStatsResponse | null>(null);
    let refreshInterval: ReturnType<typeof setInterval> | null = null;
    let activeReplaySession = $state<EventReplayStatusResponse | null>(null);
    let replayCheckInterval: ReturnType<typeof setInterval> | null = null;
    let replayPreview = $state<{ eventId: string; total_events: number; events_preview?: EventResponse[] } | null>(null);
    let showReplayPreview = $state(false);
    let showExportMenu = $state(false);

    // User overview modal state
    let showUserOverview = $state(false);
    let userOverviewLoading = $state(false);
    let selectedUserId = $state<string | null>(null);
    let userOverview = $state<AdminUserOverview | null>(null);

    // Filters
    let filters = $state({
        event_types: [] as string[],
        aggregate_id: '',
        correlation_id: '',
        user_id: '',
        service_name: '',
        search_text: '',
        start_time: '',
        end_time: ''
    });

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

    let totalPages = $derived(Math.ceil(totalEvents / pageSize));
    let skip = $derived((currentPage - 1) * pageSize);
    
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
        const data = unwrapOr(await browseEventsApiV1AdminEventsBrowsePost({
            body: {
                filters: {
                    ...filters,
                    start_time: filters.start_time ? new Date(filters.start_time).toISOString() : null,
                    end_time: filters.end_time ? new Date(filters.end_time).toISOString() : null
                },
                skip,
                limit: pageSize,
                sort_by: 'timestamp',
                sort_order: -1
            }
        }), null);
        loading = false;
        events = data?.events || [];
        totalEvents = data?.total || 0;
    }

    async function loadStats(): Promise<void> {
        stats = unwrapOr(await getEventStatsApiV1AdminEventsStatsGet({ query: { hours: 24 } }), null);
    }

    async function loadEventDetail(eventId: string): Promise<void> {
        selectedEvent = unwrapOr(await getEventDetailApiV1AdminEventsEventIdGet({ path: { event_id: eventId } }), null);
    }

    async function checkReplayStatus(sessionId: string): Promise<void> {
        const status = unwrapOr(await getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet({
            path: { session_id: sessionId }
        }), null);
        if (!status) {
            if (replayCheckInterval) { clearInterval(replayCheckInterval); replayCheckInterval = null; }
            return;
        }
        activeReplaySession = status;

        if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
            if (replayCheckInterval) { clearInterval(replayCheckInterval); replayCheckInterval = null; }
            if (status.status === 'completed') {
                addToast(`Replay completed! Processed ${status.replayed_events} events successfully.`, 'success');
            } else if (status.status === 'failed') {
                addToast(`Replay failed: ${status.error || 'Unknown error'}`, 'error');
            }
        }
    }

    async function replayEvent(eventId: string, dryRun: boolean = true): Promise<void> {
        if (!dryRun && !confirm('Are you sure you want to replay this event? This will re-process the event through the system.')) {
            return;
        }

        const response = unwrap(await replayEventsApiV1AdminEventsReplayPost({
            body: { event_ids: [eventId], dry_run: dryRun }
        }));

        if (dryRun) {
            if (response?.events_preview && response.events_preview.length > 0) {
                replayPreview = { ...response, eventId: eventId };
                showReplayPreview = true;
            } else {
                addToast(`Dry run: ${response?.total_events} events would be replayed`, 'info');
            }
        } else {
            addToast(`Replay scheduled! Tracking progress...`, 'success');
            if (response?.session_id) {
                activeReplaySession = {
                    session_id: response.session_id,
                    status: 'scheduled',
                    total_events: response.total_events,
                    replayed_events: 0,
                    progress_percentage: 0
                };
                checkReplayStatus(response.session_id);
                replayCheckInterval = setInterval(() => { checkReplayStatus(response.session_id); }, 2000);
            }
            selectedEvent = null;
        }
    }

    async function deleteEvent(eventId: string): Promise<void> {
        if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) return;
        unwrap(await deleteEventApiV1AdminEventsEventIdDelete({ path: { event_id: eventId } }));
        addToast('Event deleted successfully', 'success');
        await Promise.all([loadEvents(), loadStats()]);
        selectedEvent = null;
    }

    function exportEvents(format: 'csv' | 'json' = 'csv'): void {
        const params = new URLSearchParams();
        if (filters.event_types.length > 0) params.append('event_types', filters.event_types.join(','));
        if (filters.start_time) params.append('start_time', new Date(filters.start_time).toISOString());
        if (filters.end_time) params.append('end_time', new Date(filters.end_time).toISOString());
        if (filters.aggregate_id) params.append('aggregate_id', filters.aggregate_id);
        if (filters.correlation_id) params.append('correlation_id', filters.correlation_id);
        if (filters.user_id) params.append('user_id', filters.user_id);
        if (filters.service_name) params.append('service_name', filters.service_name);

        window.open(`/api/v1/admin/events/export/${format}?${params.toString()}`, '_blank');
        addToast(`Starting ${format.toUpperCase()} export...`, 'info');
    }

    async function openUserOverview(userId: string): Promise<void> {
        if (!userId) return;
        selectedUserId = userId;
        userOverview = null;
        showUserOverview = true;
        userOverviewLoading = true;
        const data = unwrapOr(await getUserOverviewApiV1AdminUsersUserIdOverviewGet({ path: { user_id: userId } }), null);
        userOverviewLoading = false;
        if (!data) { showUserOverview = false; return; }
        userOverview = data;
    }

    function getEventTypeColor(eventType: string): string {
        if (eventType.includes('.completed') || eventType.includes('.succeeded')) return 'text-green-600 dark:text-green-400';
        if (eventType.includes('.failed') || eventType.includes('.timeout')) return 'text-red-600 dark:text-red-400';
        if (eventType.includes('.started') || eventType.includes('.running')) return 'text-blue-600 dark:text-blue-400';
        if (eventType.includes('.requested')) return 'text-purple-600 dark:text-purple-400';
        if (eventType.includes('.created')) return 'text-indigo-600 dark:text-indigo-400';
        if (eventType.includes('.terminated')) return 'text-orange-600 dark:text-orange-400';
        return 'text-gray-600 dark:text-gray-400';
    }

    function getEventTypeLabel(eventType: string): string {
        // For execution.requested, show icon only (with tooltip)
        if (eventType === 'execution.requested') {
            return '';
        }
        
        // For all other events, show full name
        const parts = eventType.split('.');
        if (parts.length === 2) {
            return `${parts[0]}.${parts[1]}`;
        }
        return eventType;
    }
    
    function clearFilters(): void {
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
    
    function getActiveFilterCount(): number {
        let count = 0;
        if (filters.event_types.length > 0) count++;
        if (filters.search_text) count++;
        if (filters.correlation_id) count++;
        if (filters.aggregate_id) count++;
        if (filters.user_id) count++;
        if (filters.service_name) count++;
        if (filters.start_time) count++;
        if (filters.end_time) count++;
        return count;
    }
    
    function hasActiveFilters(): boolean {
        return getActiveFilterCount() > 0;
    }

    function getActiveFilterSummary(): string {
        const items: string[] = [];
        if (filters.event_types.length > 0) {
            items.push(`${filters.event_types.length} event type${filters.event_types.length > 1 ? 's' : ''}`);
        }
        if (filters.search_text) items.push('search');
        if (filters.correlation_id) items.push('correlation');
        if (filters.aggregate_id) items.push('aggregate');
        if (filters.user_id) items.push('user');
        if (filters.service_name) items.push('service');
        if (filters.start_time || filters.end_time) items.push('time range');
        return items;
    }
</script>

<AdminLayout path="/admin/events">
    <div class="container mx-auto px-4 pb-8">
        <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold">Event Browser</h1>
            
            <div class="flex flex-wrap gap-2">
                <button
                    onclick={() => showFilters = !showFilters}
                    class="btn btn-sm sm:btn-md flex items-center gap-1 sm:gap-2 transition-all duration-200"
                    class:btn-primary={showFilters}
                    class:btn-secondary-outline={!showFilters}
                    class:ring-2={showFilters}
                    class:ring-primary={showFilters}
                    class:ring-offset-2={showFilters}
                    class:dark:ring-offset-dark-bg-default={showFilters}
                >
                    <span class="transition-transform duration-200" class:rotate-180={showFilters}>
                        <Filter size={16} />
                    </span>
                    <span class="hidden sm:inline">Filters</span>
                    {#if hasActiveFilters()}
                        <span class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {showFilters ? 'bg-white text-primary' : 'bg-primary text-white'}">
                            {getActiveFilterCount()}
                        </span>
                    {/if}
                </button>
                
                <!-- Export dropdown -->
                <div class="relative">
                    <button
                        onclick={() => showExportMenu = !showExportMenu}
                        onblur={() => setTimeout(() => showExportMenu = false, 200)}
                        class="btn btn-sm sm:btn-md btn-secondary-outline flex items-center gap-1 sm:gap-2"
                    >
                        <Download size={16} />
                        <span class="hidden sm:inline">Export</span>
                        <ChevronRight size={12} class="ml-1 rotate-90" />
                    </button>

                    {#if showExportMenu}
                        <div class="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-50">
                            <button
                                onclick={() => { exportEvents('csv'); showExportMenu = false; }}
                                class="w-full px-4 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 rounded-t-lg transition-colors"
                            >
                                <FileText size={16} class="text-green-600 dark:text-green-400" />
                                <span>Export as CSV</span>
                            </button>
                            <button
                                onclick={() => { exportEvents('json'); showExportMenu = false; }}
                                class="w-full px-4 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 rounded-b-lg transition-colors"
                            >
                                <Code size={16} class="text-blue-600 dark:text-blue-400" />
                                <span>Export as JSON</span>
                            </button>
                        </div>
                    {/if}
                </div>

                <button
                    onclick={loadEvents}
                    class="btn btn-sm sm:btn-md btn-primary flex items-center gap-1 sm:gap-2"
                    disabled={loading}
                >
                    {#if loading}
                        <Spinner size="small" />
                    {:else}
                        <RefreshCw size={16} />
                    {/if}
                    <span class="hidden sm:inline">Refresh</span>
                </button>
            </div>
        </div>
        
        {#if activeReplaySession}
            <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6 relative">
                <!-- Close button in top right corner -->
                <button
                    onclick={() => activeReplaySession = null}
                    class="absolute top-2 right-2 p-1 hover:bg-blue-100 dark:hover:bg-blue-800 rounded-lg transition-colors"
                    title="Close"
                >
                    <X size={20} class="text-blue-600 dark:text-blue-400" />
                </button>
                
                <div class="flex items-center justify-between mb-2 pr-8">
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
                    <div class="mt-2">
                        <div class="text-sm text-red-600 dark:text-red-400">
                            Failed: {activeReplaySession.failed_events} events
                        </div>
                        {#if activeReplaySession.error_message}
                            <div class="mt-1 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded">
                                <p class="text-xs text-red-700 dark:text-red-300 font-mono">
                                    Error: {activeReplaySession.error_message}
                                </p>
                            </div>
                        {/if}
                        {#if activeReplaySession.failed_event_errors && activeReplaySession.failed_event_errors.length > 0}
                            <div class="mt-2 space-y-1">
                                {#each activeReplaySession.failed_event_errors as error}
                                    <div class="p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-xs">
                                        <div class="font-mono text-gray-600 dark:text-gray-400">{error.event_id}</div>
                                        <div class="text-red-700 dark:text-red-300 mt-1">{error.error}</div>
                                    </div>
                                {/each}
                            </div>
                        {/if}
                    </div>
                {/if}
                
                {#if activeReplaySession.execution_results && activeReplaySession.execution_results.length > 0}
                    <div class="mt-4 border-t border-blue-200 dark:border-blue-800 pt-3">
                        <h4 class="text-sm font-semibold text-blue-900 dark:text-blue-100 mb-2">Execution Results:</h4>
                        <div class="space-y-2">
                            {#each activeReplaySession.execution_results as result}
                                <div class="bg-white dark:bg-gray-800 rounded p-2 text-sm">
                                    <div class="flex justify-between items-start">
                                        <div>
                                            <span class="font-mono text-xs text-gray-500">{result.execution_id}</span>
                                            <div class="flex items-center gap-2 mt-1">
                                                <span class={`px-2 py-0.5 rounded text-xs ${
                                                    result.status === 'completed' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' :
                                                    result.status === 'failed' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' :
                                                    'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
                                                }`}>
                                                    {result.status}
                                                </span>
                                                {#if result.execution_time}
                                                    <span class="text-gray-500 dark:text-gray-400">
                                                        {result.execution_time.toFixed(2)}s
                                                    </span>
                                                {/if}
                                            </div>
                                        </div>
                                        {#if result.output || result.errors}
                                            <div class="text-right">
                                                {#if result.output}
                                                    <div class="font-mono text-green-600 dark:text-green-400">
                                                        Output: {result.output}
                                                    </div>
                                                {/if}
                                                {#if result.errors}
                                                    <div class="font-mono text-red-600 dark:text-red-400">
                                                        Error: {result.errors}
                                                    </div>
                                                {/if}
                                            </div>
                                        {/if}
                                    </div>
                                </div>
                            {/each}
                        </div>
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
        
        {#if !showFilters && hasActiveFilters()}
            <div class="mb-4 flex flex-wrap items-center gap-2">
                <span class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted">Active filters:</span>
                {#each getActiveFilterSummary() as filter}
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary-light">
                        {filter}
                    </span>
                {/each}
                <button
                    onclick={clearFilters}
                    class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
                >
                    <X size={12} class="mr-1" />
                    Clear all
                </button>
            </div>
        {/if}
        
        {#if showFilters}
            <div class="card mb-6">
                <div class="p-4">
                    <div class="flex items-center justify-between mb-3">
                        <h3 class="text-sm font-semibold text-fg-default dark:text-dark-fg-default uppercase tracking-wide">Filter Events</h3>
                        <div class="flex gap-2">
                            <button
                                onclick={clearFilters}
                                class="btn btn-ghost btn-sm"
                            >
                                Clear All
                            </button>
                            <button
                                onclick={() => { currentPage = 1; loadEvents(); }}
                                class="btn btn-primary btn-sm"
                            >
                                Apply
                            </button>
                        </div>
                    </div>
                    
                    <div class="space-y-3">
                        <!-- Primary filters row -->
                        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                            <div class="lg:col-span-1">
                                <label for="event-types-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Event Types
                                </label>
                                <select
                                    id="event-types-filter"
                                    bind:value={filters.event_types}
                                    multiple
                                    class="form-select-standard text-sm h-20"
                                    title="Hold Ctrl/Cmd to select multiple"
                                >
                                    {#each eventTypes as type}
                                        <option value={type} class="text-xs">{type}</option>
                                    {/each}
                                </select>
                            </div>

                            <div>
                                <label for="search-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Search
                                </label>
                                <input
                                    id="search-filter"
                                    type="text"
                                    bind:value={filters.search_text}
                                    placeholder="Search events..."
                                    class="form-input-standard text-sm"
                                />
                            </div>

                            <div>
                                <label for="correlation-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Correlation ID
                                </label>
                                <input
                                    id="correlation-filter"
                                    type="text"
                                    bind:value={filters.correlation_id}
                                    placeholder="req_abc123"
                                    class="form-input-standard text-sm font-mono"
                                />
                            </div>

                            <div>
                                <label for="aggregate-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Aggregate ID
                                </label>
                                <input
                                    id="aggregate-filter"
                                    type="text"
                                    bind:value={filters.aggregate_id}
                                    placeholder="exec_id"
                                    class="form-input-standard text-sm font-mono"
                                />
                            </div>

                            <div>
                                <label for="user-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    User ID
                                </label>
                                <input
                                    id="user-filter"
                                    type="text"
                                    bind:value={filters.user_id}
                                    placeholder="user_123"
                                    class="form-input-standard text-sm font-mono"
                                />
                            </div>
                        </div>
                        
                        <!-- Secondary filters row - collapsible on mobile -->
                        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            <div>
                                <label for="service-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Service
                                </label>
                                <input
                                    id="service-filter"
                                    type="text"
                                    bind:value={filters.service_name}
                                    placeholder="execution-service"
                                    class="form-input-standard text-sm"
                                />
                            </div>

                            <div>
                                <label for="start-time-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Start Time
                                </label>
                                <input
                                    id="start-time-filter"
                                    type="datetime-local"
                                    bind:value={filters.start_time}
                                    class="form-input-standard text-sm"
                                />
                            </div>

                            <div>
                                <label for="end-time-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    End Time
                                </label>
                                <input
                                    id="end-time-filter"
                                    type="datetime-local"
                                    bind:value={filters.end_time}
                                    class="form-input-standard text-sm"
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        {/if}
        
        <div class="card">
            <div class="p-6">
                <div class="mb-4">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-2">
                        Events
                    </h3>
                </div>
                
                <!-- Desktop view - Table -->
                <div class="hidden md:block overflow-x-auto">
                    <table class="w-full divide-y divide-border-default dark:divide-dark-border-default">
                        <thead class="bg-neutral-50 dark:bg-neutral-900">
                            <tr>
                                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Time</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Type</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider hidden lg:table-cell">User</th>
                                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider hidden xl:table-cell">Service</th>
                                <th class="px-3 py-2 text-center text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-bg-default dark:bg-dark-bg-default divide-y divide-border-default dark:divide-dark-border-default">
                            {#each events || [] as event}
                                <tr
                                    class="hover:bg-neutral-50 dark:hover:bg-neutral-800 cursor-pointer transition-colors border-b border-border-default dark:border-dark-border-default"
                                    onclick={() => loadEventDetail(event.event_id)}
                                    onkeydown={(e) => e.key === 'Enter' && loadEventDetail(event.event_id)}
                                    tabindex="0"
                                    role="button"
                                    aria-label="View event details"
                                >
                                    <td class="px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                                        <div class="text-xs text-fg-muted dark:text-dark-fg-muted">
                                            {new Date(event.timestamp).toLocaleDateString()}
                                        </div>
                                        <div class="text-sm">
                                            {new Date(event.timestamp).toLocaleTimeString()}
                                        </div>
                                    </td>
                                    <td class="px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                                        <div class="relative group">
                                            <span class={`${getEventTypeColor(event.event_type)} shrink-0 cursor-help`}>
                                                <EventTypeIcon eventType={event.event_type} />
                                            </span>
                                            <!-- Tooltip on hover -->
                                            <div class="absolute z-10 invisible group-hover:visible bg-gray-900 text-white text-xs rounded py-1 px-2 left-0 top-8 min-w-max">
                                                <div class="font-medium">{event.event_type}</div>
                                                <div class="text-gray-400 text-[10px] font-mono mt-0.5">
                                                    {event.event_id.slice(0, 8)}...
                                                </div>
                                                <!-- Tooltip arrow -->
                                                <div class="absolute -top-1 left-2 w-2 h-2 bg-gray-900 transform rotate-45"></div>
                                            </div>
                                        </div>
                                    </td>
                                    <td class="table-cell-sm hidden lg:table-cell">
                                        {#if event.metadata?.user_id}
                                            <button
                                                class="text-blue-600 dark:text-blue-400 hover:underline text-left"
                                                title="View user overview"
                                                onclick={(e) => { e.stopPropagation(); openUserOverview(event.metadata.user_id); }}
                                            >
                                                <div class="font-mono text-xs truncate">
                                                    {event.metadata.user_id}
                                                </div>
                                            </button>
                                        {:else}
                                            <span class="text-fg-muted dark:text-dark-fg-muted">-</span>
                                        {/if}
                                    </td>
                                    <td class="table-cell-sm hidden xl:table-cell">
                                        <div class="truncate" title={event.metadata?.service_name || '-'}>
                                            {event.metadata?.service_name || '-'}
                                        </div>
                                    </td>
                                    <td class="px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                                        <div class="flex gap-1 justify-center">
                                            <button
                                                onclick={(e) => { e.stopPropagation(); replayEvent(event.event_id); }}
                                                class="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                                                title="Preview replay"
                                            >
                                                <Eye size={16} />
                                            </button>
                                            <button
                                                onclick={(e) => { e.stopPropagation(); replayEvent(event.event_id, false); }}
                                                class="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-blue-600 dark:text-blue-400"
                                                title="Replay"
                                            >
                                                <Play size={16} />
                                            </button>
                                            <button
                                                onclick={(e) => { e.stopPropagation(); deleteEvent(event.event_id); }}
                                                class="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-red-600 dark:text-red-400"
                                                title="Delete"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>

                <!-- Mobile view - Cards -->
                <div class="md:hidden space-y-3">
                    {#each events || [] as event}
                        <div
                            class="mobile-card"
                            onclick={() => loadEventDetail(event.event_id)}
                            onkeydown={(e) => e.key === 'Enter' && loadEventDetail(event.event_id)}
                            tabindex="0"
                            role="button"
                            aria-label="View event details"
                        >
                            <div class="flex justify-between items-start mb-2">
                                <div class="flex-1 min-w-0">
                                    <div class="flex items-center gap-2">
                                        <div class="relative group">
                                            <span class={`${getEventTypeColor(event.event_type)} shrink-0 cursor-help`}>
                                                <EventTypeIcon eventType={event.event_type} />
                                            </span>
                                            <!-- Mobile tooltip -->
                                            <div class="absolute z-10 invisible group-hover:visible bg-gray-900 text-white text-xs rounded py-1 px-2 left-0 top-7 min-w-max">
                                                <div class="font-medium">{event.event_type}</div>
                                                <div class="text-gray-400 text-[10px] font-mono mt-0.5">
                                                    {event.event_id.slice(0, 8)}...
                                                </div>
                                                <div class="absolute -top-1 left-2 w-2 h-2 bg-gray-900 transform rotate-45"></div>
                                            </div>
                                        </div>
                                        <div class="text-sm text-fg-muted dark:text-dark-fg-muted">
                                            {formatTimestamp(event.timestamp)}
                                        </div>
                                    </div>
                                </div>
                                <div class="flex gap-1 ml-2">
                                    <button
                                        onclick={(e) => { e.stopPropagation(); replayEvent(event.event_id); }}
                                        class="btn btn-ghost btn-xs p-1"
                                        title="Preview replay"
                                    >
                                        <Eye size={16} />
                                    </button>
                                    <button
                                        onclick={(e) => { e.stopPropagation(); replayEvent(event.event_id, false); }}
                                        class="btn btn-ghost btn-xs p-1 text-blue-600 dark:text-blue-400"
                                        title="Replay"
                                    >
                                        <Play size={16} />
                                    </button>
                                    <button
                                        onclick={(e) => { e.stopPropagation(); deleteEvent(event.event_id); }}
                                        class="btn btn-ghost btn-xs p-1 text-red-600 dark:text-red-400"
                                        title="Delete"
                                    >
                                        <Trash2 size={16} />
                                    </button>
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-2 text-sm">
                                <div>
                                    <span class="text-fg-muted dark:text-dark-fg-muted">User:</span>
                                    {#if event.metadata?.user_id}
                                        <button
                                            class="ml-1 text-blue-600 dark:text-blue-400 hover:underline font-mono"
                                            title="View user overview"
                                            onclick={(e) => { e.stopPropagation(); openUserOverview(event.metadata.user_id); }}
                                        >
                                            {event.metadata.user_id}
                                        </button>
                                    {:else}
                                        <span class="ml-1 font-mono">-</span>
                                    {/if}
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
                        <div class="empty-state">
                            No events found
                        </div>
                    {/if}
                    
                    <!-- Pagination controls -->
                    {#if totalEvents > 0}
                    <div class="divider pt-4 mt-4">
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                            <!-- Left side container -->
                            <div class="flex items-center gap-4">
                                <!-- Page size selector -->
                                <div class="flex items-center gap-2">
                                    <label for="events-page-size" class="text-sm text-fg-muted dark:text-dark-fg-muted">Show:</label>
                                    <select
                                        id="events-page-size"
                                        bind:value={pageSize}
                                        onchange={() => { currentPage = 1; loadEvents(); }}
                                        class="px-3 py-1.5 pr-8 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                                        style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 fill=%22none%22 viewBox=%220 0 20 20%22><path stroke=%22%236b7280%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22 stroke-width=%221.5%22 d=%22M6 8l4 4 4-4%22/></svg>'); background-repeat: no-repeat; background-position: right 0.5rem center; background-size: 16px;"
                                    >
                                        <option value={10}>10</option>
                                        <option value={25}>25</option>
                                        <option value={50}>50</option>
                                        <option value={100}>100</option>
                                    </select>
                                    <span class="text-sm text-fg-muted dark:text-dark-fg-muted">per page</span>
                                </div>
                                
                                <!-- Pagination controls -->
                                {#if totalPages > 1}
                                <div class="flex items-center gap-1">
                                <!-- First page -->
                                <button
                                    onclick={() => { currentPage = 1; loadEvents(); }}
                                    disabled={currentPage === 1}
                                    class="pagination-button"
                                    title="First page"
                                >
                                    <ChevronsLeft size={16} />
                                </button>

                                <!-- Previous page -->
                                <button
                                    onclick={() => { currentPage--; loadEvents(); }}
                                    disabled={currentPage === 1}
                                    class="pagination-button"
                                    title="Previous page"
                                >
                                    <ChevronLeft size={16} />
                                </button>

                                <!-- Page numbers -->
                                <div class="pagination-text">
                                    <span class="font-medium">{currentPage}</span>
                                    <span class="text-fg-muted dark:text-dark-fg-muted mx-1">/</span>
                                    <span class="font-medium">{totalPages}</span>
                                </div>

                                <!-- Next page -->
                                <button
                                    onclick={() => { currentPage++; loadEvents(); }}
                                    disabled={currentPage === totalPages}
                                    class="pagination-button"
                                    title="Next page"
                                >
                                    <ChevronRight size={16} />
                                </button>

                                <!-- Last page -->
                                <button
                                    onclick={() => { currentPage = totalPages; loadEvents(); }}
                                    disabled={currentPage === totalPages}
                                    class="pagination-button"
                                    title="Last page"
                                >
                                    <ChevronsRight size={16} />
                                </button>
                                </div>
                                {/if}
                            </div>
                            
                            <!-- Info text at the right -->
                            <div class="text-xs sm:text-sm text-fg-muted dark:text-dark-fg-muted">
                                Showing {(currentPage - 1) * pageSize + 1} to {Math.min(currentPage * pageSize, totalEvents)} of {totalEvents} events
                            </div>
                        </div>
                    </div>
                    {/if}
            </div>
        </div>
    </div>

    <Modal open={!!selectedEvent} title="Event Details" onClose={() => selectedEvent = null} size="lg">
        {#if selectedEvent}
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
                                <td class="px-4 py-2">
                                    <div class="flex items-center gap-2">
                                        <span class={`${getEventTypeColor(selectedEvent.event.event_type)} shrink-0`} title={selectedEvent.event.event_type}>
                                            <EventTypeIcon eventType={selectedEvent.event.event_type} />
                                        </span>
                                        <span class={getEventTypeColor(selectedEvent.event.event_type)}>
                                            {selectedEvent.event.event_type}
                                        </span>
                                    </div>
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
                    <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default">{JSON.stringify(selectedEvent.event.metadata, null, 2)}</pre>
                </div>

                <div>
                    <h4 class="font-semibold mb-2">Payload</h4>
                    <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default">{JSON.stringify(selectedEvent.event.payload, null, 2)}</pre>
                </div>

                {#if selectedEvent.related_events && selectedEvent.related_events.length > 0}
                    <div>
                        <h4 class="font-semibold mb-2">Related Events</h4>
                        <div class="space-y-1">
                            {#each selectedEvent.related_events || [] as related}
                                <button
                                    onclick={() => loadEventDetail(related.event_id)}
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
        {/if}

        {#snippet footer()}
            <button
                onclick={() => selectedEvent && replayEvent(selectedEvent.event.event_id, false)}
                class="btn btn-primary"
            >
                Replay Event
            </button>
            <button
                onclick={() => selectedEvent = null}
                class="btn btn-secondary-outline"
            >
                Close
            </button>
        {/snippet}
    </Modal>

    <!-- Replay Preview Modal -->
    <Modal open={showReplayPreview && !!replayPreview} title="Replay Preview" onClose={() => { showReplayPreview = false; replayPreview = null; }} size="md">
        {#if replayPreview}
            <p class="text-sm text-gray-500 dark:text-gray-400 -mt-2 mb-4">
                Review the events that will be replayed
            </p>

            <div class="mb-4">
                <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                    <div class="flex items-center justify-between">
                        <span class="font-semibold text-blue-900 dark:text-blue-100">
                            {replayPreview.total_events} event{replayPreview.total_events !== 1 ? 's' : ''} will be replayed
                        </span>
                        <span class="text-sm text-blue-700 dark:text-blue-300">Dry Run</span>
                    </div>
                </div>
            </div>

            {#if replayPreview.events_preview && replayPreview.events_preview.length > 0}
                <div class="space-y-3">
                    <h3 class="font-medium text-gray-900 dark:text-white mb-2">Events to Replay:</h3>
                    {#each replayPreview.events_preview as event}
                        <div class="bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
                            <div class="flex justify-between items-start">
                                <div>
                                    <div class="font-mono text-xs text-gray-500 dark:text-gray-400 mb-1">{event.event_id}</div>
                                    <div class="font-medium text-gray-900 dark:text-white">{event.event_type}</div>
                                    {#if event.aggregate_id}
                                        <div class="text-sm text-gray-500 dark:text-gray-400 mt-1">Aggregate: {event.aggregate_id}</div>
                                    {/if}
                                </div>
                                <div class="text-sm text-gray-500 dark:text-gray-400">{formatTimestamp(event.timestamp)}</div>
                            </div>
                        </div>
                    {/each}
                </div>
            {/if}

            <div class="mt-6 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
                <div class="flex">
                    <AlertTriangle size={20} class="text-yellow-400 dark:text-yellow-300 mt-0.5 shrink-0" />
                    <div class="ml-3">
                        <h3 class="text-sm font-medium text-yellow-800 dark:text-yellow-200">Warning</h3>
                        <div class="mt-1 text-sm text-yellow-700 dark:text-yellow-300">
                            Replaying events will re-process them through the system. This may trigger new executions
                            and create duplicate results if the events have already been processed.
                        </div>
                    </div>
                </div>
            </div>
        {/if}

        {#snippet footer()}
            <button
                onclick={() => {
                    showReplayPreview = false;
                    if (replayPreview) replayEvent(replayPreview.eventId, false);
                }}
                class="btn btn-primary"
            >
                Proceed with Replay
            </button>
            <button
                onclick={() => { showReplayPreview = false; replayPreview = null; }}
                class="btn btn-secondary-outline"
            >
                Cancel
            </button>
        {/snippet}
    </Modal>

    <!-- User Overview Modal -->
    <Modal open={showUserOverview} title="User Overview" onClose={() => showUserOverview = false} size="lg">
        {#if userOverviewLoading}
            <div class="flex items-center justify-center py-10">
                <Spinner />
            </div>
        {:else if userOverview}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- User info -->
                <div>
                    <h3 class="font-semibold mb-3 text-fg-default dark:text-dark-fg-default">Profile</h3>
                    <div class="space-y-2 text-sm">
                        <div><span class="text-fg-muted dark:text-dark-fg-muted">User ID:</span> <span class="font-mono">{userOverview.user.user_id}</span></div>
                        <div><span class="text-fg-muted dark:text-dark-fg-muted">Username:</span> {userOverview.user.username}</div>
                        <div><span class="text-fg-muted dark:text-dark-fg-muted">Email:</span> {userOverview.user.email}</div>
                        <div><span class="text-fg-muted dark:text-dark-fg-muted">Role:</span> {userOverview.user.role}</div>
                        <div><span class="text-fg-muted dark:text-dark-fg-muted">Active:</span> {userOverview.user.is_active ? 'Yes' : 'No'}</div>
                        <div><span class="text-fg-muted dark:text-dark-fg-muted">Superuser:</span> {userOverview.user.is_superuser ? 'Yes' : 'No'}</div>
                    </div>
                    {#if userOverview.rate_limit_summary}
                        <div class="mt-4">
                            <h4 class="font-medium mb-2 text-fg-default dark:text-dark-fg-default">Rate Limits</h4>
                            <div class="text-sm space-y-1">
                                <div><span class="text-fg-muted dark:text-dark-fg-muted">Bypass:</span> {userOverview.rate_limit_summary.bypass_rate_limit ? 'Yes' : 'No'}</div>
                                <div><span class="text-fg-muted dark:text-dark-fg-muted">Global Multiplier:</span> {userOverview.rate_limit_summary.global_multiplier ?? 1.0}</div>
                                <div><span class="text-fg-muted dark:text-dark-fg-muted">Custom Rules:</span> {userOverview.rate_limit_summary.has_custom_limits ? 'Yes' : 'No'}</div>
                            </div>
                        </div>
                    {/if}
                </div>

                <!-- Stats -->
                <div>
                    <h3 class="font-semibold mb-3 text-fg-default dark:text-dark-fg-default">Execution Stats (last 24h)</h3>
                    <div class="grid grid-cols-2 gap-3">
                        <div class="p-3 rounded-lg bg-green-50 dark:bg-green-900/20">
                            <div class="text-xs text-green-700 dark:text-green-300">Succeeded</div>
                            <div class="text-xl font-semibold text-green-800 dark:text-green-200">{userOverview.derived_counts.succeeded}</div>
                        </div>
                        <div class="p-3 rounded-lg bg-red-50 dark:bg-red-900/20">
                            <div class="text-xs text-red-700 dark:text-red-300">Failed</div>
                            <div class="text-xl font-semibold text-red-800 dark:text-red-200">{userOverview.derived_counts.failed}</div>
                        </div>
                        <div class="p-3 rounded-lg bg-yellow-50 dark:bg-yellow-900/20">
                            <div class="text-xs text-yellow-700 dark:text-yellow-300">Timeout</div>
                            <div class="text-xl font-semibold text-yellow-800 dark:text-yellow-200">{userOverview.derived_counts.timeout}</div>
                        </div>
                        <div class="p-3 rounded-lg bg-gray-100 dark:bg-gray-800">
                            <div class="text-xs text-gray-700 dark:text-gray-300">Cancelled</div>
                            <div class="text-xl font-semibold text-gray-900 dark:text-gray-100">{userOverview.derived_counts.cancelled}</div>
                        </div>
                    </div>
                    <div class="mt-3 text-sm text-fg-muted dark:text-dark-fg-muted">
                        Terminal Total: <span class="font-semibold text-fg-default dark:text-dark-fg-default">{userOverview.derived_counts.terminal_total}</span>
                    </div>
                    <div class="mt-2 text-sm text-fg-muted dark:text-dark-fg-muted">
                        Total Events: <span class="font-semibold text-fg-default dark:text-dark-fg-default">{userOverview.stats.total_events}</span>
                    </div>
                </div>
            </div>

            {#if userOverview.recent_events && userOverview.recent_events.length > 0}
                <div class="mt-6">
                    <h3 class="font-semibold mb-2 text-fg-default dark:text-dark-fg-default">Recent Execution Events</h3>
                    <div class="space-y-1 max-h-48 overflow-auto">
                        {#each userOverview.recent_events as ev}
                            <div class="flex justify-between items-center p-2 bg-neutral-50 dark:bg-neutral-800 rounded">
                                <div class="text-sm">
                                    <span class={getEventTypeColor(ev.event_type)}>{getEventTypeLabel(ev.event_type) || ev.event_type}</span>
                                    <span class="ml-2 font-mono text-xs text-fg-muted dark:text-dark-fg-muted">{ev.aggregate_id || '-'}</span>
                                </div>
                                <div class="text-xs text-fg-muted dark:text-dark-fg-muted">{formatTimestamp(ev.timestamp)}</div>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}
        {:else}
            <div class="text-sm text-fg-muted dark:text-dark-fg-muted">No data available</div>
        {/if}

        {#snippet footer()}
            <a href="/admin/users" class="btn btn-outline">Open User Management</a>
        {/snippet}
    </Modal>
</AdminLayout>
