import { createMutation, createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
import type { PaginationState } from '@tanstack/svelte-table';
import {
    browseEventsApiV1AdminEventsBrowsePostOptions,
    getEventStatsApiV1AdminEventsStatsGetOptions,
    getEventDetailApiV1AdminEventsEventIdGetOptions,
    getUserOverviewApiV1AdminUsersUserIdOverviewGetOptions,
    replayEventsApiV1AdminEventsReplayPostMutation,
    deleteEventApiV1AdminEventsEventIdDeleteMutation,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    client,
    ExportFormat,
    ReplayStatus,
    zExportEventsApiV1AdminEventsExportExportFormatGetQuery,
    type ExportEventsApiV1AdminEventsExportExportFormatGetData,
    type EventBrowseResponse,
    type EventFilter,
    type EventDetailResponse,
    type EventReplayResponse,
    type EventReplayStatusResponse,
} from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('EventsStore');
const POLL_INTERVAL_MS = 30_000;

export type BrowsedEvent = EventBrowseResponse['events'][number];
export type ReplayPreview = Pick<EventReplayResponse, 'total_events' | 'events_preview'> & { eventId: string };

class EventsStore {
    // The filter form edits `filters`; the list and the export follow `appliedFilters`, set by Apply
    filters = $state<EventFilter>({});
    appliedFilters = $state<EventFilter>({});

    pagination = $state<PaginationState>({ pageIndex: 0, pageSize: 10 });

    selectedEvent = $state<EventDetailResponse | null>(null);
    overviewUserId = $state<string | null>(null);

    activeReplaySession = $state<EventReplayStatusResponse | null>(null);
    replayPreview = $state<ReplayPreview | null>(null);
    private replayAbortController: AbortController | null = null;

    #queryClient = useQueryClient();

    list = createQuery(() => ({
        ...browseEventsApiV1AdminEventsBrowsePostOptions({
            body: {
                filters: this.appliedFilters,
                skip: this.pagination.pageIndex * this.pagination.pageSize,
                limit: this.pagination.pageSize,
            },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: POLL_INTERVAL_MS,
    }));

    stats = createQuery(() => ({
        ...getEventStatsApiV1AdminEventsStatsGetOptions(),
        refetchInterval: POLL_INTERVAL_MS,
    }));

    userOverview = createQuery(() => ({
        ...getUserOverviewApiV1AdminUsersUserIdOverviewGetOptions({ path: { user_id: this.overviewUserId ?? '' } }),
        enabled: this.overviewUserId !== null,
    }));

    #replay = createMutation(() => replayEventsApiV1AdminEventsReplayPostMutation());

    #delete = createMutation(() => ({
        ...deleteEventApiV1AdminEventsEventIdDeleteMutation(),
        onSuccess: () => {
            toast.success('Event deleted successfully');
            return this.refresh();
        },
    }));

    events = $derived(this.list.data?.events ?? []);
    totalEvents = $derived(this.list.data?.total ?? 0);

    // The browse key needs a body, so there's no key prefix to invalidate; other pages refetch when opened anyway
    async refresh(): Promise<void> {
        await Promise.all([this.list.refetch(), this.stats.refetch()]);
    }

    async openEventDetail(eventId: string): Promise<void> {
        // A failed load already showed the interceptor's toast, so the modal just stays closed
        this.selectedEvent = await this.#queryClient
            .query(getEventDetailApiV1AdminEventsEventIdGetOptions({ path: { event_id: eventId } }))
            .catch(() => null);
    }

    openUserOverview(userId: string): void {
        if (userId) this.overviewUserId = userId;
    }

    replayEvent(eventId: string, dryRun: boolean = true): void {
        if (
            !dryRun &&
            !confirm('Are you sure you want to replay this event? This will re-process the event through the system.')
        ) {
            return;
        }

        this.#replay.mutate(
            { body: { event_ids: [eventId], dry_run: dryRun } },
            {
                onSuccess: (response) => {
                    this.#onReplayed(eventId, dryRun, response);
                },
            },
        );
    }

    #onReplayed(eventId: string, dryRun: boolean, response: EventReplayResponse): void {
        if (dryRun) {
            if (response.events_preview && response.events_preview.length > 0) {
                this.replayPreview = {
                    eventId,
                    total_events: response.total_events,
                    events_preview: response.events_preview,
                };
            } else {
                toast.info(`Dry run: ${response.total_events} events would be replayed`);
            }
            return;
        }

        toast.success(`Replay scheduled! Tracking progress...`);
        if (response.session_id) this.connectReplayStream(response.session_id);
    }

    connectReplayStream(sessionId: string): void {
        this.disconnectReplayStream();
        const controller = new AbortController();
        this.replayAbortController = controller;
        this.#startReplayStream(sessionId, controller.signal).catch((err: unknown) => {
            if (!controller.signal.aborted) log.warn('Replay status stream failed:', err);
        });
    }

    async #startReplayStream(sessionId: string, signal: AbortSignal): Promise<void> {
        const { stream } = await streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet({
            path: { session_id: sessionId },
            signal,
            sseMaxRetryAttempts: 3,
        });

        // The server sends the whole session first and on every change, and closes the stream once it ends
        for await (const status of stream) {
            if (signal.aborted) return;
            this.activeReplaySession = status;
            if (status.status === ReplayStatus.COMPLETED) {
                toast.success(`Replay completed! Processed ${status.replayed_events} events successfully.`);
            } else if (status.status === ReplayStatus.FAILED) {
                toast.error(`Replay failed: ${status.errors?.[0]?.error || 'Unknown error'}`);
            }
        }
    }

    disconnectReplayStream(): void {
        if (this.replayAbortController) {
            this.replayAbortController.abort();
            this.replayAbortController = null;
        }
    }

    dismissReplay(): void {
        this.disconnectReplayStream();
        this.activeReplaySession = null;
    }

    deleteEvent(eventId: string): void {
        if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) return;
        this.#delete.mutate({ path: { event_id: eventId } });
    }

    exportEvents(format: ExportFormat = ExportFormat.CSV): void {
        // A plain navigation lets the browser stream a large export to disk instead of buffering it
        const url = client.buildUrl<ExportEventsApiV1AdminEventsExportExportFormatGetData>({
            url: '/api/v1/admin/events/export/{export_format}',
            path: { export_format: format },
            query: zExportEventsApiV1AdminEventsExportExportFormatGetQuery.parse(this.appliedFilters),
        });
        window.open(url, '_blank');
        toast.info(`Starting ${format} export...`);
    }

    applyFilters(): void {
        this.appliedFilters = $state.snapshot(this.filters);
        this.pagination = { ...this.pagination, pageIndex: 0 };
    }

    clearFilters(): void {
        this.filters = {};
        this.applyFilters();
    }

    cleanup(): void {
        this.disconnectReplayStream();
    }
}

export function createEventsStore(): EventsStore {
    return new EventsStore();
}
