import { createMutation, createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
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
    type ExportEventsApiV1AdminEventsExportExportFormatGetData,
    type EventBrowseResponse,
    type EventFilter,
    type EventDetailResponse,
    type EventReplayResponse,
    type EventReplayStatusResponse,
} from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';
import { parseISO } from 'date-fns';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('EventsStore');
const POLL_INTERVAL_MS = 30_000;

export type BrowsedEvent = EventBrowseResponse['events'][number];
export type ReplayPreview = Pick<EventReplayResponse, 'total_events' | 'events_preview'> & { eventId: string };

function toIso(value: string | null | undefined): string | null {
    return value ? parseISO(value).toISOString() : null;
}

class EventsStore {
    // The filter form edits `filters`; the list and the export follow `appliedFilters`, set by Apply
    filters = $state<EventFilter>({});
    appliedFilters = $state<EventFilter>({});

    currentPage = $state(1);
    pageSize = $state(10);

    selectedEvent = $state<EventDetailResponse | null>(null);
    overviewUserId = $state<string | null>(null);

    activeReplaySession = $state<EventReplayStatusResponse | null>(null);
    replayPreview = $state<ReplayPreview | null>(null);
    private replayAbortController: AbortController | null = null;

    #queryClient = useQueryClient();

    list = createQuery(() => ({
        ...browseEventsApiV1AdminEventsBrowsePostOptions({
            body: {
                filters: {
                    ...this.appliedFilters,
                    start_time: toIso(this.appliedFilters.start_time),
                    end_time: toIso(this.appliedFilters.end_time),
                },
                skip: (this.currentPage - 1) * this.pageSize,
                limit: this.pageSize,
            },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: POLL_INTERVAL_MS,
    }));

    stats = createQuery(() => ({
        ...getEventStatsApiV1AdminEventsStatsGetOptions({ query: { hours: 24 } }),
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
    totalPages = $derived(Math.ceil(this.totalEvents / this.pageSize));

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
        const sessionId = response.session_id;
        if (!sessionId) return;
        this.activeReplaySession = {
            session_id: sessionId,
            status: 'scheduled',
            total_events: response.total_events,
            replayed_events: 0,
            progress_percentage: 0,
            failed_events: 0,
            skipped_events: 0,
            replay_id: response.replay_id,
            created_at: new Date().toISOString(),
            started_at: null,
            completed_at: null,
            errors: null,
            estimated_completion: null,
            execution_results: null,
        };
        this.connectReplayStream(sessionId);
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

        for await (const status of stream) {
            if (signal.aborted || !this.activeReplaySession) return;
            const pct = status.total_events > 0 ? Math.round((status.replayed_events / status.total_events) * 100) : 0;
            this.activeReplaySession = { ...this.activeReplaySession, ...status, progress_percentage: pct };

            if (status.status === 'completed') {
                toast.success(`Replay completed! Processed ${status.replayed_events} events successfully.`);
            } else if (status.status === 'failed') {
                toast.error(`Replay failed: ${status.errors?.[0]?.error || 'Unknown error'}`);
            }
            if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
                this.disconnectReplayStream();
                return;
            }
        }
    }

    disconnectReplayStream(): void {
        if (this.replayAbortController) {
            this.replayAbortController.abort();
            this.replayAbortController = null;
        }
    }

    deleteEvent(eventId: string): void {
        if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) return;
        this.#delete.mutate({ path: { event_id: eventId } });
    }

    exportEvents(format: ExportFormat = ExportFormat.CSV): void {
        const { event_types, start_time, end_time, aggregate_id, user_id, service_name } = this.appliedFilters;
        // A plain navigation lets the browser stream a large export to disk instead of buffering it
        const url = client.buildUrl<ExportEventsApiV1AdminEventsExportExportFormatGetData>({
            url: '/api/v1/admin/events/export/{export_format}',
            path: { export_format: format },
            query: {
                event_types: event_types?.length ? event_types : undefined,
                start_time: toIso(start_time) ?? undefined,
                end_time: toIso(end_time) ?? undefined,
                aggregate_id: aggregate_id || undefined,
                user_id: user_id || undefined,
                service_name: service_name || undefined,
            },
        });
        window.open(url, '_blank');
        toast.info(`Starting ${format.toUpperCase()} export...`);
    }

    applyFilters(): void {
        this.appliedFilters = $state.snapshot(this.filters);
        this.currentPage = 1;
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
