<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import type { EventDetailResponse } from '$lib/api';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Spinner from '$components/Spinner.svelte';
    import { FilterPanel } from '$components/admin';
    import {
        EventStatsCards,
        EventFilters,
        EventsTable,
        EventDetailsModal,
        ReplayPreviewModal,
        ReplayProgressBanner,
        UserOverviewModal
    } from '$components/admin/events';
    import {
        hasActiveFilters,
        getActiveFilterCount,
        getActiveFilterSummary,
    } from '$lib/admin/events';
    import {
        Filter, Download, RefreshCw, X,
        ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight,
        FileText, Code
    } from '@lucide/svelte';
    import { createEventsStore } from '$lib/admin/stores/eventsStore.svelte';

    const store = createEventsStore();

    // UI-only state
    let showFilters = $state(false);
    let selectedEvent = $state<EventDetailResponse | null>(null);
    let showExportMenu = $state(false);
    let showUserOverview = $state(false);

    let totalPages = $derived(Math.ceil(store.totalEvents / store.pagination.pageSize));

    // Show replay preview modal when store populates replayPreview
    let showReplayPreview = $derived(store.replayPreview !== null);

    async function loadEventDetail(eventId: string): Promise<void> {
        selectedEvent = await store.loadEventDetail(eventId);
    }

    function handlePreviewReplay(eventId: string): void {
        store.replayEvent(eventId, true);
    }

    function handleReplay(eventId: string): void {
        store.replayEvent(eventId, false);
    }

    function handleReplayFromModal(eventId: string): void {
        selectedEvent = null;
        store.replayEvent(eventId, false);
    }

    function handleReplayConfirm(eventId: string): void {
        store.replayEvent(eventId, false);
    }

    async function handleUserOverview(userId: string): Promise<void> {
        showUserOverview = true;
        await store.openUserOverview(userId);
        if (!store.userOverview) { showUserOverview = false; }
    }

    onMount(() => {
        store.loadAll();
    });

    onDestroy(() => store.cleanup());
</script>

<AdminLayout path="/admin/events">
    <div class="container mx-auto px-4 pb-8">
        <!-- Header -->
        <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold">Event Browser</h1>

            <div class="flex flex-wrap gap-2">
                <button type="button"
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
                    {#if hasActiveFilters(store.filters)}
                        <span class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {showFilters ? 'bg-white text-primary' : 'bg-primary text-white'}">
                            {getActiveFilterCount(store.filters)}
                        </span>
                    {/if}
                </button>

                <!-- Export dropdown -->
                <div class="relative">
                    <button type="button"
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
                            <button type="button"
                                onclick={() => { store.exportEvents('csv'); showExportMenu = false; }}
                                class="w-full px-4 py-2 text-left hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover flex items-center gap-2 rounded-t-lg transition-colors"
                            >
                                <FileText size={16} class="text-green-600 dark:text-green-400" />
                                <span>Export as CSV</span>
                            </button>
                            <button type="button"
                                onclick={() => { store.exportEvents('json'); showExportMenu = false; }}
                                class="w-full px-4 py-2 text-left hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover flex items-center gap-2 rounded-b-lg transition-colors"
                            >
                                <Code size={16} class="text-blue-600 dark:text-blue-400" />
                                <span>Export as JSON</span>
                            </button>
                        </div>
                    {/if}
                </div>

                <button type="button" onclick={() => store.loadEvents()} class="btn btn-sm sm:btn-md btn-primary flex items-center gap-1 sm:gap-2" disabled={store.loading}>
                    {#if store.loading}<Spinner size="small" />{:else}<RefreshCw size={16} />{/if}
                    <span class="hidden sm:inline">Refresh</span>
                </button>
            </div>
        </div>

        <ReplayProgressBanner session={store.activeReplaySession} onClose={() => store.activeReplaySession = null} />

        <EventStatsCards stats={store.stats} totalEvents={store.totalEvents} />

        <!-- Active filters summary (when filters panel closed) -->
        {#if !showFilters && hasActiveFilters(store.filters)}
            <div class="mb-4 flex flex-wrap items-center gap-2">
                <span class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted">Active filters:</span>
                {#each getActiveFilterSummary(store.filters) as filter}
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary-light">
                        {filter}
                    </span>
                {/each}
                <button type="button"
                    onclick={() => store.clearFilters()}
                    class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
                >
                    <X size={12} class="mr-1" />
                    Clear all
                </button>
            </div>
        {/if}

        {#if showFilters}
            <EventFilters bind:filters={store.filters} onApply={() => store.applyFilters()} onClear={() => store.clearFilters()} />
        {/if}

        <!-- Events table -->
        <div class="card">
            <div class="p-6">
                <div class="mb-4">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-2">Events</h3>
                </div>

                <EventsTable
                    events={store.events}
                    onViewDetails={loadEventDetail}
                    onPreviewReplay={handlePreviewReplay}
                    onReplay={handleReplay}
                    onDelete={(id) => store.deleteEvent(id)}
                    onViewUser={handleUserOverview}
                />

                <!-- Pagination -->
                {#if store.totalEvents > 0}
                    <div class="divider pt-4 mt-4">
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                            <div class="flex items-center gap-4">
                                <div class="flex items-center gap-2">
                                    <label for="events-page-size" class="text-sm text-fg-muted dark:text-dark-fg-muted">Show:</label>
                                    <select
                                        id="events-page-size"
                                        bind:value={store.pagination.pageSize}
                                        onchange={() => { store.pagination.currentPage = 1; store.loadEvents(); }}
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
                                        <button type="button" onclick={() => { store.pagination.currentPage = 1; store.loadEvents(); }} disabled={store.pagination.currentPage === 1} class="pagination-button" title="First page">
                                            <ChevronsLeft size={16} />
                                        </button>
                                        <button type="button" onclick={() => { store.pagination.currentPage--; store.loadEvents(); }} disabled={store.pagination.currentPage === 1} class="pagination-button" title="Previous page">
                                            <ChevronLeft size={16} />
                                        </button>
                                        <div class="pagination-text">
                                            <span class="font-medium">{store.pagination.currentPage}</span>
                                            <span class="text-fg-muted dark:text-dark-fg-muted mx-1">/</span>
                                            <span class="font-medium">{totalPages}</span>
                                        </div>
                                        <button type="button" onclick={() => { store.pagination.currentPage++; store.loadEvents(); }} disabled={store.pagination.currentPage === totalPages} class="pagination-button" title="Next page">
                                            <ChevronRight size={16} />
                                        </button>
                                        <button type="button" onclick={() => { store.pagination.currentPage = totalPages; store.loadEvents(); }} disabled={store.pagination.currentPage === totalPages} class="pagination-button" title="Last page">
                                            <ChevronsRight size={16} />
                                        </button>
                                    </div>
                                {/if}
                            </div>

                            <div class="text-xs sm:text-sm text-fg-muted dark:text-dark-fg-muted">
                                Showing {(store.pagination.currentPage - 1) * store.pagination.pageSize + 1} to {Math.min(store.pagination.currentPage * store.pagination.pageSize, store.totalEvents)} of {store.totalEvents} events
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

{#if showReplayPreview && store.replayPreview}
    <ReplayPreviewModal
        preview={store.replayPreview}
        open={showReplayPreview}
        onClose={() => { store.replayPreview = null; }}
        onConfirm={handleReplayConfirm}
    />
{/if}

{#if showUserOverview}
    <UserOverviewModal
        overview={store.userOverview}
        loading={store.userOverviewLoading}
        open={showUserOverview}
        onClose={() => showUserOverview = false}
    />
{/if}
