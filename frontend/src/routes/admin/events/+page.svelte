<script lang="ts">
    import { createMutation, createQuery, keepPreviousData } from '@tanstack/svelte-query';
    import { toast } from 'svelte-sonner';
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
    import type { ReplayPreview } from '#components/admin/events/ReplayPreviewModal.svelte';
    import { hasActiveFilters, getActiveFilterCount, getActiveFilterSummary } from '#lib/admin/events/index.ts';
    import { Funnel, Download, RefreshCw, X, ChevronRight, FileText, Code } from '@lucide/svelte';
    import { DropdownMenu } from 'bits-ui';
    import {
        browseEventsApiV1AdminEventsBrowsePostOptions,
        client,
        deleteEventApiV1AdminEventsEventIdDeleteMutation,
        ExportFormat,
        getEventStatsApiV1AdminEventsStatsGetOptions,
        replayEventsApiV1AdminEventsReplayPostMutation,
        zExportEventsApiV1AdminEventsExportExportFormatGetQuery,
        type EventFilter,
        type ExportEventsApiV1AdminEventsExportExportFormatGetData,
    } from '#lib/api/index.ts';

    const POLL_INTERVAL_MS = 30_000;

    const exportIcons: Record<ExportFormat, { icon: typeof FileText; color: string }> = {
        [ExportFormat.CSV]: { icon: FileText, color: 'text-green-600 dark:text-green-400' },
        [ExportFormat.JSON]: { icon: Code, color: 'text-blue-600 dark:text-blue-400' },
    };

    // The filter form edits `filters`; the list and the export follow `applied`, set by Apply
    let filters = $state<EventFilter>({});
    let applied = $state<EventFilter>({});
    let showFilters = $state(false);
    let selectedEventId = $state<string | null>(null);
    let overviewUserId = $state<string | null>(null);
    let replayPreview = $state<ReplayPreview | null>(null);
    let replaySessionId = $state<string | null>(null);

    // Applied filters go back to the first page, since the old one may not exist under them
    let pageSize = $state(10);
    let pageIndex = $derived.by(() => {
        void applied;
        return 0;
    });

    const list = createQuery(() => ({
        ...browseEventsApiV1AdminEventsBrowsePostOptions({
            body: { filters: applied, skip: pageIndex * pageSize, limit: pageSize },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: POLL_INTERVAL_MS,
    }));
    const stats = createQuery(() => ({
        ...getEventStatsApiV1AdminEventsStatsGetOptions(),
        refetchInterval: POLL_INTERVAL_MS,
    }));

    // The browse key carries its body, so there's no key prefix to invalidate
    const refresh = () => Promise.all([list.refetch(), stats.refetch()]);

    const remove = createMutation(() => ({
        ...deleteEventApiV1AdminEventsEventIdDeleteMutation(),
        onSuccess: () => {
            toast.success('Event deleted successfully');
            return refresh();
        },
    }));
    const replay = createMutation(() => replayEventsApiV1AdminEventsReplayPostMutation());

    function deleteEvent(eventId: string): void {
        if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) return;
        remove.mutate({ path: { event_id: eventId } });
    }

    function replayEvent(eventId: string, dryRun: boolean): void {
        const message =
            'Are you sure you want to replay this event? This will re-process the event through the system.';
        if (!dryRun && !confirm(message)) return;
        replay.mutate(
            { body: { event_ids: [eventId], dry_run: dryRun } },
            {
                onSuccess: ({ total_events, events_preview, session_id }) => {
                    if (!dryRun) {
                        toast.success('Replay scheduled! Tracking progress...');
                        replaySessionId = session_id ?? null;
                    } else if (events_preview?.length) {
                        replayPreview = { eventId, total_events, events_preview };
                    } else {
                        toast.info(`Dry run: ${total_events} events would be replayed`);
                    }
                },
            },
        );
    }

    function exportEvents(format: ExportFormat): void {
        // A plain navigation lets the browser stream a large export to disk instead of buffering it
        const url = client.buildUrl<ExportEventsApiV1AdminEventsExportExportFormatGetData>({
            url: '/api/v1/admin/events/export/{export_format}',
            path: { export_format: format },
            query: zExportEventsApiV1AdminEventsExportExportFormatGetQuery.parse(applied),
        });
        window.open(url, '_blank');
        toast.info(`Starting ${format} export...`);
    }

    function applyFilters(): void {
        applied = $state.snapshot(filters);
    }

    function clearFilters(): void {
        filters = {};
        applyFilters();
    }
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
                {#if hasActiveFilters(applied)}
                    <span
                        class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {showFilters
                            ? 'bg-white text-primary'
                            : 'bg-primary text-white'}"
                    >
                        {getActiveFilterCount(applied)}
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
                            <DropdownMenu.Item class="floating-item" onSelect={() => exportEvents(format)}>
                                <Icon size={16} class={exportIcons[format].color} />Export as {format}
                            </DropdownMenu.Item>
                        {/each}
                    </DropdownMenu.Content>
                </DropdownMenu.Portal>
            </DropdownMenu.Root>

            <button
                type="button"
                onclick={refresh}
                class="btn btn-sm btn-primary flex items-center gap-1 sm:gap-2"
                disabled={list.isFetching}
            >
                {#if list.isFetching}<Spinner size="small" />{:else}<RefreshCw size={16} />{/if}
                <span class="hidden sm:inline">Refresh</span>
            </button>
        </div>
    </div>

    {#if replaySessionId}
        <ReplayProgressBanner sessionId={replaySessionId} onClose={() => (replaySessionId = null)} />
    {/if}

    <EventStatsCards stats={stats.data ?? null} totalEvents={list.data?.total ?? 0} />

    <!-- Active filters summary (when filters panel closed) -->
    {#if !showFilters && hasActiveFilters(applied)}
        <div class="mb-4 flex flex-wrap items-center gap-2">
            <span class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted">Active filters:</span>
            {#each getActiveFilterSummary(applied) as filter}
                <span
                    class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary-light"
                >
                    {filter}
                </span>
            {/each}
            <button
                type="button"
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
                events={list.data?.events ?? []}
                rowCount={list.data?.total ?? 0}
                bind:pagination={
                    () => ({ pageIndex, pageSize }),
                    (next) => {
                        pageSize = next.pageSize;
                        pageIndex = next.pageIndex;
                    }
                }
                loading={list.isPending}
                onViewDetails={(id) => (selectedEventId = id)}
                onPreviewReplay={(id) => replayEvent(id, true)}
                onReplay={(id) => replayEvent(id, false)}
                onDelete={deleteEvent}
                onViewUser={(id) => (overviewUserId = id || null)}
            />
        </div>
    </div>
</div>

<!-- Modals -->
{#if selectedEventId}
    <EventDetailsModal
        eventId={selectedEventId}
        onClose={() => (selectedEventId = null)}
        onReplay={(id) => {
            selectedEventId = null;
            replayEvent(id, false);
        }}
        onViewRelated={(id) => (selectedEventId = id)}
    />
{/if}

{#if replayPreview}
    <ReplayPreviewModal
        preview={replayPreview}
        open
        onClose={() => (replayPreview = null)}
        onConfirm={(id) => replayEvent(id, false)}
    />
{/if}

{#if overviewUserId}
    <UserOverviewModal userId={overviewUserId} onClose={() => (overviewUserId = null)} />
{/if}
