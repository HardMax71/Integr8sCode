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
    import AdminLayout from './AdminLayout.svelte';
    import Spinner from '../../components/Spinner.svelte';
    import { FilterPanel } from '../../components/admin';
    import {
        EventStatsCards,
        EventFilters,
        EventsTable,
        EventDetailsModal,
        ReplayPreviewModal,
        ReplayProgressBanner,
        UserOverviewModal
    } from '../../components/admin/events';
    import {
        createDefaultEventFilters,
        hasActiveFilters,
        getActiveFilterCount,
        getActiveFilterSummary,
        type EventFilters as EventFiltersType
    } from '../../lib/admin/events';
    import {
        Filter, Download, RefreshCw, X,
        ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight,
        FileText, Code
    } from '@lucide/svelte';

    // State
    let events = $state<EventResponse[]>([]);
    let loading = $state(false);
    let totalEvents = $state(0);
    let stats = $state<EventStatsResponse | null>(null);

    // Pagination
    let currentPage = $state(1);
    let pageSize = $state(10);
    let totalPages = $derived(Math.ceil(totalEvents / pageSize));
    let skip = $derived((currentPage - 1) * pageSize);

    // Filters
    let showFilters = $state(false);
    let filters = $state<EventFiltersType>(createDefaultEventFilters());

    // Modals
    let selectedEvent = $state<EventDetailResponse | null>(null);
    let showExportMenu = $state(false);

    // Replay state
    let activeReplaySession = $state<EventReplayStatusResponse | null>(null);
    let replayCheckInterval: ReturnType<typeof setInterval> | null = null;
    let replayPreview = $state<{ eventId: string; total_events: number; events_preview?: EventResponse[] } | null>(null);
    let showReplayPreview = $state(false);

    // User overview modal
    let showUserOverview = $state(false);
    let userOverviewLoading = $state(false);
    let userOverview = $state<AdminUserOverview | null>(null);

    // Auto-refresh
    let refreshInterval: ReturnType<typeof setInterval> | null = null;

    onMount(() => {
        loadEvents();
        loadStats();
        refreshInterval = setInterval(() => {
            loadEvents();
            loadStats();
        }, 30000);
    });

    onDestroy(() => {
        if (refreshInterval) clearInterval(refreshInterval);
        if (replayCheckInterval) clearInterval(replayCheckInterval);
    });

    async function loadEvents(): Promise<void> {
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
                replayPreview = { ...response, eventId };
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
        userOverview = null;
        showUserOverview = true;
        userOverviewLoading = true;
        const data = unwrapOr(await getUserOverviewApiV1AdminUsersUserIdOverviewGet({ path: { user_id: userId } }), null);
        userOverviewLoading = false;
        if (!data) { showUserOverview = false; return; }
        userOverview = data;
    }

    function clearFilters(): void {
        filters = createDefaultEventFilters();
        currentPage = 1;
        loadEvents();
    }

    function applyFilters(): void {
        currentPage = 1;
        loadEvents();
    }

    function handlePreviewReplay(eventId: string): void {
        replayEvent(eventId, true);
    }

    function handleReplay(eventId: string): void {
        replayEvent(eventId, false);
    }

    function handleReplayFromModal(eventId: string): void {
        selectedEvent = null;
        replayEvent(eventId, false);
    }

    function handleReplayConfirm(eventId: string): void {
        replayEvent(eventId, false);
    }
</script>

<AdminLayout path="/admin/events">
    <div class="container mx-auto px-4 pb-8">
        <!-- Header -->
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
                    {#if hasActiveFilters(filters)}
                        <span class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {showFilters ? 'bg-white text-primary' : 'bg-primary text-white'}">
                            {getActiveFilterCount(filters)}
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
                        <div class="absolute right-0 mt-2 w-48 bg-surface-overlay dark:bg-dark-surface-overlay rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 z-50">
                            <button
                                onclick={() => { exportEvents('csv'); showExportMenu = false; }}
                                class="w-full px-4 py-2 text-left hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover flex items-center gap-2 rounded-t-lg transition-colors"
                            >
                                <FileText size={16} class="text-green-600 dark:text-green-400" />
                                <span>Export as CSV</span>
                            </button>
                            <button
                                onclick={() => { exportEvents('json'); showExportMenu = false; }}
                                class="w-full px-4 py-2 text-left hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover flex items-center gap-2 rounded-b-lg transition-colors"
                            >
                                <Code size={16} class="text-blue-600 dark:text-blue-400" />
                                <span>Export as JSON</span>
                            </button>
                        </div>
                    {/if}
                </div>

                <button onclick={loadEvents} class="btn btn-sm sm:btn-md btn-primary flex items-center gap-1 sm:gap-2" disabled={loading}>
                    {#if loading}<Spinner size="small" />{:else}<RefreshCw size={16} />{/if}
                    <span class="hidden sm:inline">Refresh</span>
                </button>
            </div>
        </div>

        <ReplayProgressBanner session={activeReplaySession} onClose={() => activeReplaySession = null} />

        <EventStatsCards {stats} {totalEvents} />

        <!-- Active filters summary (when filters panel closed) -->
        {#if !showFilters && hasActiveFilters(filters)}
            <div class="mb-4 flex flex-wrap items-center gap-2">
                <span class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted">Active filters:</span>
                {#each getActiveFilterSummary(filters) as filter}
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
            <EventFilters bind:filters onApply={applyFilters} onClear={clearFilters} />
        {/if}

        <!-- Events table -->
        <div class="card">
            <div class="p-6">
                <div class="mb-4">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-2">Events</h3>
                </div>

                <EventsTable
                    {events}
                    onViewDetails={loadEventDetail}
                    onPreviewReplay={handlePreviewReplay}
                    onReplay={handleReplay}
                    onDelete={deleteEvent}
                    onViewUser={openUserOverview}
                />

                <!-- Pagination -->
                {#if totalEvents > 0}
                    <div class="divider pt-4 mt-4">
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                            <div class="flex items-center gap-4">
                                <div class="flex items-center gap-2">
                                    <label for="events-page-size" class="text-sm text-fg-muted dark:text-dark-fg-muted">Show:</label>
                                    <select
                                        id="events-page-size"
                                        bind:value={pageSize}
                                        onchange={() => { currentPage = 1; loadEvents(); }}
                                        class="px-3 py-1.5 pr-8 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-surface-overlay dark:bg-dark-surface-overlay text-neutral-900 dark:text-neutral-100 text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                                        style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 fill=%22none%22 viewBox=%220 0 20 20%22><path stroke=%22%236b7280%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22 stroke-width=%221.5%22 d=%22M6 8l4 4 4-4%22/></svg>'); background-repeat: no-repeat; background-position: right 0.5rem center; background-size: 16px;"
                                    >
                                        <option value={10}>10</option>
                                        <option value={25}>25</option>
                                        <option value={50}>50</option>
                                        <option value={100}>100</option>
                                    </select>
                                    <span class="text-sm text-fg-muted dark:text-dark-fg-muted">per page</span>
                                </div>

                                {#if totalPages > 1}
                                    <div class="flex items-center gap-1">
                                        <button onclick={() => { currentPage = 1; loadEvents(); }} disabled={currentPage === 1} class="pagination-button" title="First page">
                                            <ChevronsLeft size={16} />
                                        </button>
                                        <button onclick={() => { currentPage--; loadEvents(); }} disabled={currentPage === 1} class="pagination-button" title="Previous page">
                                            <ChevronLeft size={16} />
                                        </button>
                                        <div class="pagination-text">
                                            <span class="font-medium">{currentPage}</span>
                                            <span class="text-fg-muted dark:text-dark-fg-muted mx-1">/</span>
                                            <span class="font-medium">{totalPages}</span>
                                        </div>
                                        <button onclick={() => { currentPage++; loadEvents(); }} disabled={currentPage === totalPages} class="pagination-button" title="Next page">
                                            <ChevronRight size={16} />
                                        </button>
                                        <button onclick={() => { currentPage = totalPages; loadEvents(); }} disabled={currentPage === totalPages} class="pagination-button" title="Last page">
                                            <ChevronsRight size={16} />
                                        </button>
                                    </div>
                                {/if}
                            </div>

                            <div class="text-xs sm:text-sm text-fg-muted dark:text-dark-fg-muted">
                                Showing {(currentPage - 1) * pageSize + 1} to {Math.min(currentPage * pageSize, totalEvents)} of {totalEvents} events
                            </div>
                        </div>
                    </div>
                {/if}
            </div>
        </div>
    </div>
</AdminLayout>

<!-- Modals -->
{#if selectedEvent}
    <EventDetailsModal
        event={selectedEvent}
        open={!!selectedEvent}
        onClose={() => selectedEvent = null}
        onReplay={handleReplayFromModal}
        onViewRelated={loadEventDetail}
    />
{/if}

{#if showReplayPreview && replayPreview}
    <ReplayPreviewModal
        preview={replayPreview}
        open={showReplayPreview && !!replayPreview}
        onClose={() => { showReplayPreview = false; replayPreview = null; }}
        onConfirm={handleReplayConfirm}
    />
{/if}

{#if showUserOverview}
    <UserOverviewModal
        overview={userOverview}
        loading={userOverviewLoading}
        open={showUserOverview}
        onClose={() => showUserOverview = false}
    />
{/if}
