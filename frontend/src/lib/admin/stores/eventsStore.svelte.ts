import {
    browseEventsApiV1AdminEventsBrowsePost,
    getEventStatsApiV1AdminEventsStatsGet,
    getEventDetailApiV1AdminEventsEventIdGet,
    replayEventsApiV1AdminEventsReplayPost,
    deleteEventApiV1AdminEventsEventIdDelete,
    getUserOverviewApiV1AdminUsersUserIdOverviewGet,
    type EventBrowseResponse,
    type EventFilter,
    type EventStatsResponse,
    type EventDetailResponse,
    type EventReplayStatusResponse,
    type EventSummary,
    type AdminUserOverview,
} from '$lib/api';
import { unwrap, unwrapOr } from '$lib/api-interceptors';
import { toast } from 'svelte-sonner';
import { createPaginationState } from '$lib/admin/pagination.svelte';

export type BrowsedEvent = EventBrowseResponse['events'][number];

class EventsStore {
    events = $state<BrowsedEvent[]>([]);
    loading = $state(false);
    totalEvents = $state(0);
    stats = $state<EventStatsResponse | null>(null);
    filters = $state<EventFilter>({});

    activeReplaySession = $state<EventReplayStatusResponse | null>(null);
    replayPreview = $state<{ eventId: string; total_events: number; events_preview?: EventSummary[] } | null>(null);
    private replayAbortController: AbortController | null = null;

    userOverview = $state<AdminUserOverview | null>(null);
    userOverviewLoading = $state(false);

    pagination = createPaginationState({ initialPageSize: 10 });

    constructor() {
        $effect(() => {
            const id = setInterval(() => this.loadAll(), 30_000);
            return () => { clearInterval(id); };
        });
    }

    async loadAll(): Promise<void> {
        await Promise.all([this.loadEvents(), this.loadStats()]);
    }

    async loadEvents(): Promise<void> {
        this.loading = true;
        const data = unwrapOr(await browseEventsApiV1AdminEventsBrowsePost({
            body: {
                filters: {
                    ...this.filters,
                    start_time: this.filters.start_time ? new Date(this.filters.start_time).toISOString() : null,
                    end_time: this.filters.end_time ? new Date(this.filters.end_time).toISOString() : null
                },
                skip: this.pagination.skip,
                limit: this.pagination.pageSize
            }
        }), null);
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
        if (!dryRun && !confirm('Are you sure you want to replay this event? This will re-process the event through the system.')) {
            return;
        }

        const response = unwrap(await replayEventsApiV1AdminEventsReplayPost({
            body: { event_ids: [eventId], dry_run: dryRun }
        }));

        if (dryRun) {
            if (response.events_preview && response.events_preview.length > 0) {
                this.replayPreview = { eventId, total_events: response.total_events, events_preview: response.events_preview };
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
        this.#startReplayStream(sessionId, controller.signal);
    }

    #startReplayStream(sessionId: string, signal: AbortSignal): void {
        const eventSource = new EventSource(`/api/v1/admin/events/replay/${sessionId}/status`);

        signal.addEventListener('abort', () => {
            eventSource.close();
        });

        eventSource.onmessage = (event: MessageEvent) => {
            if (signal.aborted) return;
            try {
                const payload = JSON.parse(event.data as string) as EventReplayStatusResponse;
                const pct = payload.total_events > 0
                    ? Math.round((payload.replayed_events / payload.total_events) * 100)
                    : 0;
                if (!this.activeReplaySession) return;
                this.activeReplaySession = {
                    ...this.activeReplaySession,
                    ...payload,
                    progress_percentage: pct,
                };

                if (payload.status === 'completed' || payload.status === 'failed' || payload.status === 'cancelled') {
                    if (payload.status === 'completed') {
                        toast.success(`Replay completed! Processed ${payload.replayed_events} events successfully.`);
                    } else if (payload.status === 'failed') {
                        toast.error(`Replay failed: ${payload.errors?.[0]?.error || 'Unknown error'}`);
                    }
                    this.disconnectReplayStream();
                }
            } catch (e) {
                if (!(e instanceof SyntaxError)) {
                    console.warn('[EventsStore] SSE parse error:', e);
                }
            }
        };

        eventSource.onerror = () => {
            if (!signal.aborted) {
                this.disconnectReplayStream();
            }
        };
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

    exportEvents(format: 'csv' | 'json' = 'csv'): void {
        const params = new URLSearchParams();
        if (this.filters.event_types?.length) params.append('event_types', this.filters.event_types.join(','));
        if (this.filters.start_time) params.append('start_time', new Date(this.filters.start_time).toISOString());
        if (this.filters.end_time) params.append('end_time', new Date(this.filters.end_time).toISOString());
        if (this.filters.aggregate_id) params.append('aggregate_id', this.filters.aggregate_id);
        if (this.filters.user_id) params.append('user_id', this.filters.user_id);
        if (this.filters.service_name) params.append('service_name', this.filters.service_name);

        window.open(`/api/v1/admin/events/export/${format}?${params.toString()}`, '_blank');
        toast.info(`Starting ${format.toUpperCase()} export...`);
    }

    async openUserOverview(userId: string): Promise<void> {
        if (!userId) return;
        this.userOverview = null;
        this.userOverviewLoading = true;
        const data = unwrapOr(await getUserOverviewApiV1AdminUsersUserIdOverviewGet({ path: { user_id: userId } }), null);
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
