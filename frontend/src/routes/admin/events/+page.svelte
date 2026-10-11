<script lang="ts">
    import { onDestroy } from 'svelte';
    import Spinner from '#components/Spinner.svelte';
    import {
        EventStatsCards,
        EventFilters,
        EventsTable,
        EventDetailsModal,
        ReplayPreviewModal,
        ReplayProgressBanner,
        UserOverviewModal,
    } from '#components/admin/events/index.ts';
    import { hasActiveFilters, getActiveFilterCount, getActiveFilterSummary } from '#lib/admin/events/index.ts';
    import { Funnel, Download, RefreshCw, X, ChevronRight, FileText, Code } from '@lucide/svelte';
    import Pagination from '#components/Pagination.svelte';
    import { createEventsStore } from '#lib/admin/stores/eventsStore.svelte.ts';

    const store = createEventsStore();

    // UI-only state
    let showFilters = $state(false);
    let showExportMenu = $state(false);

    // Show replay preview modal when store populates replayPreview
    let showReplayPreview = $derived(store.replayPreview !== null);

    function handleReplay(eventId: string, closeModal = false): void {
        if (closeModal) store.selectedEvent = null;
        store.replayEvent(eventId, false);
    }

    onDestroy(() => store.cleanup());
</script>

<svelte:document
    onclick={(e) => {
        if (showExportMenu && !(e.target as Element)?.closest('.export-dropdown')) {
            showExportMenu = false;
        }
    }}
/>

<div class="container mx-auto px-4 pb-8">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
        <h1 class="text-2xl sm:text-3xl font-bold">Event Browser</h1>

        <div class="flex flex-wrap gap-2">
            <button
                type="button"
                onclick={() => (showFilters = !showFilters)}
                class="btn btn-sm sm:btn-md flex items-center gap-1 sm:gap-2 transition-all duration-200"
                class:btn-primary={showFilters}
                class:btn-secondary-outline={!showFilters}
                class:ring-2={showFilters}
                class:ring-primary={showFilters}
                class:ring-offset-2={showFilters}
                class:dark:ring-offset-dark-bg-default={showFilters}
            >
                <span class="transition-transform duration-200" class:rotate-180={showFilters}>
                    <Funnel size={16} />
                </span>
                <span class="hidden sm:inline">Filters</span>
                {#if hasActiveFilters(store.appliedFilters)}
                    <span
                        class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {showFilters
                            ? 'bg-white text-primary'
                            : 'bg-primary text-white'}"
                    >
                        {getActiveFilterCount(store.appliedFilters)}
                    </span>
                {/if}
            </button>

            <!-- Export dropdown -->
            <div class="relative export-dropdown">
                <button
                    type="button"
                    onclick={() => (showExportMenu = !showExportMenu)}
                    class="btn btn-sm sm:btn-md btn-secondary-outline flex items-center gap-1 sm:gap-2"
                >
                    <Download size={16} />
                    <span class="hidden sm:inline">Export</span>
                    <ChevronRight size={12} class="ml-1 rotate-90" />
                </button>

                {#if showExportMenu}
                    <div
                        class="absolute right-0 mt-2 w-48 bg-surface-overlay dark:bg-dark-surface-overlay rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 z-50"
                    >
                        <button
                            type="button"
                            onclick={() => {
                                store.exportEvents('csv');
                                showExportMenu = false;
                            }}
                            class="w-full px-4 py-2 text-left hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover flex items-center gap-2 rounded-t-lg transition-colors"
                        >
                            <FileText size={16} class="text-green-600 dark:text-green-400" />
                            <span>Export as CSV</span>
                        </button>
                        <button
                            type="button"
                            onclick={() => {
                                store.exportEvents('json');
                                showExportMenu = false;
                            }}
                            class="w-full px-4 py-2 text-left hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover flex items-center gap-2 rounded-b-lg transition-colors"
                        >
                            <Code size={16} class="text-blue-600 dark:text-blue-400" />
                            <span>Export as JSON</span>
                        </button>
                    </div>
                {/if}
            </div>

            <button
                type="button"
                onclick={() => store.refresh()}
                class="btn btn-sm sm:btn-md btn-primary flex items-center gap-1 sm:gap-2"
                disabled={store.list.isFetching}
            >
                {#if store.list.isFetching}<Spinner size="small" />{:else}<RefreshCw size={16} />{/if}
                <span class="hidden sm:inline">Refresh</span>
            </button>
        </div>
    </div>

    <ReplayProgressBanner session={store.activeReplaySession} onClose={() => (store.activeReplaySession = null)} />

    <EventStatsCards stats={store.stats.data ?? null} totalEvents={store.totalEvents} />

    <!-- Active filters summary (when filters panel closed) -->
    {#if !showFilters && hasActiveFilters(store.appliedFilters)}
        <div class="mb-4 flex flex-wrap items-center gap-2">
            <span class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted">Active filters:</span>
            {#each getActiveFilterSummary(store.appliedFilters) as filter}
                <span
                    class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary-light"
                >
                    {filter}
                </span>
            {/each}
            <button
                type="button"
                onclick={() => store.clearFilters()}
                class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
            >
                <X size={12} class="mr-1" />
                Clear all
            </button>
        </div>
    {/if}

    {#if showFilters}
        <EventFilters
            bind:filters={store.filters}
            onApply={() => store.applyFilters()}
            onClear={() => store.clearFilters()}
        />
    {/if}

    <!-- Events table -->
    <div class="card">
        <div class="p-6">
            <div class="mb-4">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-2">Events</h3>
            </div>

            <EventsTable
                events={store.events}
                onViewDetails={(id) => store.openEventDetail(id)}
                onPreviewReplay={(id) => store.replayEvent(id, true)}
                onReplay={handleReplay}
                onDelete={(id) => store.deleteEvent(id)}
                onViewUser={(id) => store.openUserOverview(id)}
            />

            <Pagination
                currentPage={store.currentPage}
                totalPages={store.totalPages}
                totalItems={store.totalEvents}
                bind:pageSize={store.pageSize}
                onPageChange={(page) => (store.currentPage = page)}
                onPageSizeChange={() => (store.currentPage = 1)}
                itemName="events"
            />
        </div>
    </div>
</div>

<!-- Modals -->
{#if store.selectedEvent}
    <EventDetailsModal
        event={store.selectedEvent}
        open={store.selectedEvent !== null}
        onClose={() => (store.selectedEvent = null)}
        onReplay={(id) => handleReplay(id, true)}
        onViewRelated={(id) => store.openEventDetail(id)}
    />
{/if}

{#if showReplayPreview && store.replayPreview}
    <ReplayPreviewModal
        preview={store.replayPreview}
        open={showReplayPreview}
        onClose={() => {
            store.replayPreview = null;
        }}
        onConfirm={handleReplay}
    />
{/if}

{#if store.overviewUserId !== null}
    <UserOverviewModal
        overview={store.userOverview.data ?? null}
        loading={store.userOverview.isPending}
        open={store.overviewUserId !== null}
        onClose={() => (store.overviewUserId = null)}
    />
{/if}
