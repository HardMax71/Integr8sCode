import {
    browseEventsApiV1AdminEventsBrowsePost,
    getEventStatsApiV1AdminEventsStatsGet,
    getEventDetailApiV1AdminEventsEventIdGet,
    replayEventsApiV1AdminEventsReplayPost,
    deleteEventApiV1AdminEventsEventIdDelete,
    getUserOverviewApiV1AdminUsersUserIdOverviewGet,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    client,
    ExportFormat,
    type ExportEventsApiV1AdminEventsExportExportFormatGetData,
    type EventBrowseResponse,
    type EventFilter,
    type EventStatsResponse,
    type EventDetailResponse,
    type EventReplayResponse,
    type EventReplayStatusResponse,
    type AdminUserOverview,
} from '$lib/api';
import { unwrap, unwrapOr } from '$lib/api-interceptors';
import { toast } from 'svelte-sonner';
import { createPaginationState } from '$lib/admin/pagination.svelte';
import { pollWhileVisible } from '$lib/admin/pollWhileVisible.svelte';
import { parseISO } from 'date-fns';
import { logger } from '$lib/logger';

const log = logger.withTag('EventsStore');
const POLL_INTERVAL_MS = 30_000;

export type BrowsedEvent = EventBrowseResponse['events'][number];
export type ReplayPreview = Pick<EventReplayResponse, 'total_events' | 'events_preview'> & { eventId: string };

class EventsStore {
    events = $state<BrowsedEvent[]>([]);
    loading = $state(false);
    totalEvents = $state(0);
    stats = $state<EventStatsResponse | null>(null);
    filters = $state<EventFilter>({});

    activeReplaySession = $state<EventReplayStatusResponse | null>(null);
    replayPreview = $state<ReplayPreview | null>(null);
    private replayAbortController: AbortController | null = null;

    userOverview = $state<AdminUserOverview | null>(null);
    userOverviewLoading = $state(false);

    pagination = createPaginationState({ initialPageSize: 10 });

    constructor() {
        pollWhileVisible(() => this.loadAll(), POLL_INTERVAL_MS);
    }

    async loadAll(): Promise<void> {
        await Promise.all([this.loadEvents(), this.loadStats()]);
    }

    async loadEvents(): Promise<void> {
        this.loading = true;
        const data = unwrapOr(
            await browseEventsApiV1AdminEventsBrowsePost({
                body: {
                    filters: {
                        ...this.filters,
                        start_time: this.filters.start_time ? parseISO(this.filters.start_time).toISOString() : null,
                        end_time: this.filters.end_time ? parseISO(this.filters.end_time).toISOString() : null,
                    },
                    skip: this.pagination.skip,
                    limit: this.pagination.pageSize,
                },
            }),
            null,
        );
        this.loading = false;
        this.events = data?.events ?? [];
        this.totalEvents = data?.total || 0;
    }

    async loadStats(): Promise<void> {
        this.stats = unwrapOr(await getEventStatsApiV1AdminEventsStatsGet({ query: { hours: 24 } }), null);
    }

    async loadEventDetail(eventId: string): Promise<EventDetailResponse | null> {
        return unwrapOr(await getEventDetailApiV1AdminEventsEventIdGet({ path: { event_id: eventId } }), null);
    }

    async replayEvent(eventId: string, dryRun: boolean = true): Promise<void> {
        if (
            !dryRun &&
            !confirm('Are you sure you want to replay this event? This will re-process the event through the system.')
        ) {
            return;
        }

        const response = unwrap(
            await replayEventsApiV1AdminEventsReplayPost({
                body: { event_ids: [eventId], dry_run: dryRun },
            }),
        );

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
        } else {
            toast.success(`Replay scheduled! Tracking progress...`);
            const sessionId = response.session_id;
            if (sessionId) {
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
        }
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

    async deleteEvent(eventId: string): Promise<void> {
        if (!confirm('Are you sure you want to delete this event? This action cannot be undone.')) return;
        unwrap(await deleteEventApiV1AdminEventsEventIdDelete({ path: { event_id: eventId } }));
        toast.success('Event deleted successfully');
        await Promise.all([this.loadEvents(), this.loadStats()]);
    }

    exportEvents(format: ExportFormat = ExportFormat.CSV): void {
        const { event_types, start_time, end_time, aggregate_id, user_id, service_name } = this.filters;
        // A plain navigation lets the browser stream a large export to disk instead of buffering it
        const url = client.buildUrl<ExportEventsApiV1AdminEventsExportExportFormatGetData>({
            url: '/api/v1/admin/events/export/{export_format}',
            path: { export_format: format },
            query: {
                event_types: event_types?.length ? event_types : undefined,
                start_time: start_time ? parseISO(start_time).toISOString() : undefined,
                end_time: end_time ? parseISO(end_time).toISOString() : undefined,
                aggregate_id: aggregate_id || undefined,
                user_id: user_id || undefined,
                service_name: service_name || undefined,
            },
        });
        window.open(url, '_blank');
        toast.info(`Starting ${format.toUpperCase()} export...`);
    }

    async openUserOverview(userId: string): Promise<void> {
        if (!userId) return;
        this.userOverview = null;
        this.userOverviewLoading = true;
        const data = unwrapOr(
            await getUserOverviewApiV1AdminUsersUserIdOverviewGet({ path: { user_id: userId } }),
            null,
        );
        this.userOverviewLoading = false;
        if (!data) return;
        this.userOverview = data;
    }

    clearFilters(): void {
        this.filters = {};
        this.pagination.currentPage = 1;
        void this.loadEvents();
    }

    applyFilters(): void {
        this.pagination.currentPage = 1;
        void this.loadEvents();
    }

    cleanup(): void {
        this.disconnectReplayStream();
    }
}

export function createEventsStore(): EventsStore {
    return new EventsStore();
}
