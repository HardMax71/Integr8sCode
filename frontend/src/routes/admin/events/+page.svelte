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
    import { DropdownMenu } from 'bits-ui';
    import { createEventsStore } from '#lib/admin/stores/eventsStore.svelte.ts';
    import { ExportFormat } from '#lib/api/index.ts';

    const store = createEventsStore();

    const exportIcons: Record<ExportFormat, { icon: typeof FileText; color: string }> = {
        [ExportFormat.CSV]: { icon: FileText, color: 'text-green-600 dark:text-green-400' },
        [ExportFormat.JSON]: { icon: Code, color: 'text-blue-600 dark:text-blue-400' },
    };

    // UI-only state
    let showFilters = $state(false);

    // Show replay preview modal when store populates replayPreview
    let showReplayPreview = $derived(store.replayPreview !== null);

    function handleReplay(eventId: string, closeModal = false): void {
        if (closeModal) store.selectedEvent = null;
        store.replayEvent(eventId, false);
    }

    onDestroy(() => store.cleanup());
</script>

<div class="container mx-auto px-4 pb-8">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
        <h1 class="text-2xl sm:text-3xl font-bold">Event Browser</h1>

        <div class="flex flex-wrap gap-2">
            <button
                type="button"
                onclick={() => (showFilters = !showFilters)}
                class="btn btn-sm flex items-center gap-1 sm:gap-2 transition-all duration-200"
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

            <DropdownMenu.Root>
                <DropdownMenu.Trigger class="btn btn-sm btn-secondary-outline flex items-center gap-1 sm:gap-2">
                    <Download size={16} />
                    <span class="hidden sm:inline">Export</span>
                    <ChevronRight size={12} class="ml-1 rotate-90" />
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                    <DropdownMenu.Content align="end" sideOffset={8} class="floating-panel w-48">
                        {#each Object.values(ExportFormat) as format (format)}
                            {@const Icon = exportIcons[format].icon}
                            <DropdownMenu.Item class="floating-item" onSelect={() => store.exportEvents(format)}>
                                <Icon size={16} class={exportIcons[format].color} />Export as {format}
                            </DropdownMenu.Item>
                        {/each}
                    </DropdownMenu.Content>
                </DropdownMenu.Portal>
            </DropdownMenu.Root>

            <button
                type="button"
                onclick={() => store.refresh()}
                class="btn btn-sm btn-primary flex items-center gap-1 sm:gap-2"
                disabled={store.list.isFetching}
            >
                {#if store.list.isFetching}<Spinner size="small" />{:else}<RefreshCw size={16} />{/if}
                <span class="hidden sm:inline">Refresh</span>
            </button>
        </div>
    </div>

    <ReplayProgressBanner session={store.activeReplaySession} onClose={() => store.dismissReplay()} />

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
                rowCount={store.totalEvents}
                bind:pagination={store.pagination}
                loading={store.list.isPending}
                onViewDetails={(id) => store.openEventDetail(id)}
                onPreviewReplay={(id) => store.replayEvent(id, true)}
                onReplay={handleReplay}
                onDelete={(id) => store.deleteEvent(id)}
                onViewUser={(id) => store.openUserOverview(id)}
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
