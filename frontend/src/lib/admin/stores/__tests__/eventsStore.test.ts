import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
    createInQueryContext,
    createMockEvent,
    createMockEventDetail,
    createMockStats,
    createMockReplayResponse,
    createMockReplayStatus,
    createMockUserOverview,
    mockApi,
} from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import {
    browseEventsApiV1AdminEventsBrowsePost,
    getEventStatsApiV1AdminEventsStatsGet,
    getEventDetailApiV1AdminEventsEventIdGet,
    replayEventsApiV1AdminEventsReplayPost,
    deleteEventApiV1AdminEventsEventIdDelete,
    getUserOverviewApiV1AdminUsersUserIdOverviewGet,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    EventType,
    ReplayStatus,
    type EventReplayResponse,
    type EventReplayStatusResponse,
} from '#lib/api/index.ts';
import { createEventsStore } from '#lib/admin/stores/eventsStore.svelte.ts';

const windowOpen = vi.fn();
const windowConfirm = vi.fn();

// Stands in for the generated SSE call: tests push statuses, and the server or an abort ends the stream
function mockReplayStream() {
    const pending: EventReplayStatusResponse[] = [];
    let wake: (() => void) | null = null;
    let signal: AbortSignal | undefined;
    let closed = false;

    async function* stream(): AsyncGenerator<EventReplayStatusResponse> {
        while (!signal?.aborted) {
            const next = pending.shift();
            if (next) {
                yield next;
                continue;
            }
            if (closed) return;
            await new Promise<void>((resolve) => (wake = resolve));
        }
    }

    const notify = () => {
        wake?.();
        wake = null;
    };

    vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).mockImplementation(async (options) => {
        signal = options.signal ?? undefined;
        signal?.addEventListener('abort', notify);
        return { stream: stream() };
    });

    return {
        push(status: EventReplayStatusResponse): void {
            pending.push(status);
            notify();
        },
        close(): void {
            closed = true;
            notify();
        },
        get signal(): AbortSignal | undefined {
            return signal;
        },
    };
}

const browseEvents = vi.mocked(browseEventsApiV1AdminEventsBrowsePost);

function lastBrowseBody() {
    return browseEvents.mock.lastCall?.[0]?.body;
}

describe('EventsStore', () => {
    let store: ReturnType<typeof createEventsStore>;
    let unmount: () => void;

    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal('open', windowOpen);
        vi.stubGlobal('confirm', windowConfirm);
        windowConfirm.mockReturnValue(true);
        mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({ events: [], total: 0, skip: 0, limit: 10 });
        mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(createMockStats());
    });

    function createStore() {
        ({ value: store, unmount } = createInQueryContext(createEventsStore));
    }

    afterEach(() => {
        vi.unstubAllGlobals();
        store?.cleanup();
    });

    describe('initial state', () => {
        it('starts with empty data and no filters', () => {
            createStore();
            expect(store.events).toEqual([]);
            expect(store.totalEvents).toBe(0);
            expect(store.stats.data).toBeUndefined();
            expect(store.filters).toEqual({});
            expect(store.appliedFilters).toEqual({});
        });
    });

    describe('queries', () => {
        it('loads events and stats', async () => {
            const events = [createMockEvent()];
            const stats = createMockStats();
            mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({ events, total: 1, skip: 0, limit: 10 });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(stats);

            createStore();

            await vi.waitFor(() => expect(store.events).toEqual(events));
            expect(store.totalEvents).toBe(1);
            await vi.waitFor(() => expect(store.stats.data).toEqual(stats));
        });

        it('sends the page as skip and limit', async () => {
            createStore();
            store.pagination = { pageIndex: 1, pageSize: 10 };

            await vi.waitFor(() => expect(lastBrowseBody()).toMatchObject({ skip: 10, limit: 10 }));
        });

        it('sends the filters only once they are applied', async () => {
            createStore();
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(1));
            store.pagination = { pageIndex: 1, pageSize: 10 };
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(2));

            store.filters = { user_id: 'user-1', aggregate_id: 'agg-1', start_time: '2026-01-02T03:04:00.000Z' };
            await vi.advanceTimersByTimeAsync(100);
            expect(browseEvents).toHaveBeenCalledTimes(2);

            store.applyFilters();

            expect(store.pagination.pageIndex).toBe(0);
            await vi.waitFor(() =>
                expect(lastBrowseBody()).toEqual({
                    filters: { user_id: 'user-1', aggregate_id: 'agg-1', start_time: '2026-01-02T03:04:00.000Z' },
                    skip: 0,
                    limit: 10,
                }),
            );
        });
    });

    describe('openEventDetail', () => {
        it('loads the event into selectedEvent', async () => {
            const detail = createMockEventDetail();
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(detail);

            createStore();
            await store.openEventDetail('evt-1');

            expect(store.selectedEvent).toEqual(detail);
            expect(vi.mocked(getEventDetailApiV1AdminEventsEventIdGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { event_id: 'evt-1' } }),
            );
        });

        it('leaves selectedEvent empty when the load fails', async () => {
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).err({ detail: 'Event not found' });

            createStore();
            await store.openEventDetail('missing');

            expect(store.selectedEvent).toBeNull();
        });
    });

    describe('replayEvent', () => {
        it('performs dry run and sets replayPreview', async () => {
            const preview = [createMockEvent()];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok(
                createMockReplayResponse({
                    dry_run: true,
                    total_events: 1,
                    session_id: null,
                    status: ReplayStatus.PREVIEW,
                    events_preview: preview,
                }),
            );

            createStore();
            store.replayEvent('evt-1', true);

            await vi.waitFor(() =>
                expect(store.replayPreview).toEqual({
                    eventId: 'evt-1',
                    total_events: 1,
                    events_preview: preview,
                }),
            );
            expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).toHaveBeenCalledWith(
                expect.objectContaining({ body: { event_ids: ['evt-1'], dry_run: true } }),
            );
            expect(windowConfirm).not.toHaveBeenCalled();
        });

        it('confirms, then shows the session as the stream reports it', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok(createMockReplayResponse());

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);

            expect(windowConfirm).toHaveBeenCalled();
            await vi.waitFor(() =>
                expect(vi.mocked(toast.success)).toHaveBeenCalledWith(expect.stringContaining('Replay scheduled')),
            );
            expect(vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { session_id: 'session-1' } }),
            );
            expect(store.activeReplaySession).toBeNull();

            const first = createMockReplayStatus();
            replay.push(first);
            await vi.waitFor(() => expect(store.activeReplaySession).toEqual(first));
        });

        it('replaces the session with each status the stream sends', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok(createMockReplayResponse());

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);
            replay.push(createMockReplayStatus());
            await vi.waitFor(() => expect(store.activeReplaySession).not.toBeNull());

            const running = createMockReplayStatus({
                status: ReplayStatus.RUNNING,
                replayed_events: 3,
                progress_percentage: 60,
            });
            replay.push(running);

            await vi.waitFor(() => expect(store.activeReplaySession).toEqual(running));
        });

        it.each([
            [ReplayStatus.COMPLETED, 'success', 'Replay completed! Processed 5 events successfully.'],
            [ReplayStatus.FAILED, 'error', 'Replay failed: boom'],
        ] as const)('reports %s when the stream ends with it', async (status, level, message) => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok(createMockReplayResponse());

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);
            const last = createMockReplayStatus({
                status,
                replayed_events: 5,
                progress_percentage: 100,
                errors: [
                    { event_id: 'evt-1', error: 'boom', error_type: 'RuntimeError', timestamp: '2026-01-01T00:00:00Z' },
                ],
            });
            replay.push(last);
            replay.close();

            await vi.waitFor(() => expect(vi.mocked(toast[level])).toHaveBeenCalledWith(message));
            expect(store.activeReplaySession).toEqual(last);
        });

        it('stops listening and hides the session when dismissed', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok(createMockReplayResponse());

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);
            replay.push(createMockReplayStatus());
            await vi.waitFor(() => expect(store.activeReplaySession).not.toBeNull());

            store.dismissReplay();

            expect(replay.signal?.aborted).toBe(true);
            expect(store.activeReplaySession).toBeNull();
        });

        it('does not replay if confirm is cancelled', async () => {
            windowConfirm.mockReturnValue(false);

            createStore();
            store.replayEvent('evt-1', false);
            await vi.advanceTimersByTimeAsync(100);

            expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).not.toHaveBeenCalled();
        });
    });

    describe('deleteEvent', () => {
        it('confirms, deletes and refetches the list and the stats', async () => {
            mockApi(deleteEventApiV1AdminEventsEventIdDelete).ok({ message: 'deleted', event_id: 'evt-1' });

            createStore();
            await vi.waitFor(() => expect(store.list.isSuccess).toBe(true));
            browseEvents.mockClear();
            vi.mocked(getEventStatsApiV1AdminEventsStatsGet).mockClear();

            store.deleteEvent('evt-1');

            expect(windowConfirm).toHaveBeenCalled();
            await vi.waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalledWith('Event deleted successfully'));
            expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { event_id: 'evt-1' } }),
            );
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(1));
            expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledTimes(1);
        });

        it('does not delete if confirm is cancelled', async () => {
            windowConfirm.mockReturnValue(false);

            createStore();
            store.deleteEvent('evt-1');
            await vi.advanceTimersByTimeAsync(100);

            expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).not.toHaveBeenCalled();
        });
    });

    describe('exportEvents', () => {
        it('opens export URL for CSV', () => {
            createStore();
            store.exportEvents('csv');

            expect(windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/csv'),
                '_blank',
            );
            expect(vi.mocked(toast.info)).toHaveBeenCalledWith('Starting csv export...');
        });

        it('opens export URL for JSON', () => {
            createStore();
            store.exportEvents('json');

            expect(windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/json'),
                '_blank',
            );
        });

        it('exports with the applied filters, not the unapplied edits', () => {
            createStore();
            store.filters = { user_id: 'user-1', aggregate_id: 'agg-1' };
            store.applyFilters();
            store.filters = { user_id: 'user-2' };
            store.exportEvents('csv');

            const url = new URL(windowOpen.mock.calls[0]![0] as string, 'https://x');
            expect(url.searchParams.get('user_id')).toBe('user-1');
            expect(url.searchParams.get('aggregate_id')).toBe('agg-1');
        });

        it('leaves out the filters the export endpoint does not take', () => {
            createStore();
            store.filters = { user_id: 'user-1', search_text: 'boom' };
            store.applyFilters();
            store.exportEvents('csv');

            const url = new URL(windowOpen.mock.calls[0]![0] as string, 'https://x');
            expect(url.searchParams.get('user_id')).toBe('user-1');
            expect(url.searchParams.has('search_text')).toBe(false);
        });

        it('sends each event type as its own query parameter, as the API expects', () => {
            createStore();
            store.filters = { event_types: [EventType.EXECUTION_REQUESTED, EventType.POD_CREATED] };
            store.applyFilters();
            store.exportEvents('csv');

            const url = windowOpen.mock.calls[0]![0] as string;
            expect(new URL(url, 'https://x').searchParams.getAll('event_types')).toEqual([
                'execution_requested',
                'pod_created',
            ]);
        });
    });

    describe('openUserOverview', () => {
        it('loads user overview', async () => {
            const overview = createMockUserOverview();
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(overview);

            createStore();
            expect(vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet)).not.toHaveBeenCalled();
            store.openUserOverview('user-1');

            await vi.waitFor(() => expect(store.userOverview.data).toEqual(overview));
            expect(store.overviewUserId).toBe('user-1');
            expect(vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { user_id: 'user-1' } }),
            );
        });

        it('skips empty userId', async () => {
            createStore();
            store.openUserOverview('');
            await vi.advanceTimersByTimeAsync(100);

            expect(store.overviewUserId).toBeNull();
            expect(vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet)).not.toHaveBeenCalled();
        });
    });

    describe('clearFilters', () => {
        it('resets the edited and applied filters and the page', () => {
            createStore();
            store.filters = { user_id: 'test' };
            store.applyFilters();
            store.pagination = { pageIndex: 2, pageSize: 10 };

            store.clearFilters();

            expect(store.filters).toEqual({});
            expect(store.appliedFilters).toEqual({});
            expect(store.pagination.pageIndex).toBe(0);
        });
    });

    describe('auto-refresh', () => {
        it('refetches events and stats every 30 seconds', async () => {
            createStore();
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(1));

            await vi.advanceTimersByTimeAsync(30000);
            expect(browseEvents).toHaveBeenCalledTimes(2);
            expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledTimes(2);

            await vi.advanceTimersByTimeAsync(30000);
            expect(browseEvents).toHaveBeenCalledTimes(3);
        });

        it('stops when the page unmounts', async () => {
            createStore();
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(1));

            unmount();
            await vi.advanceTimersByTimeAsync(60000);

            expect(browseEvents).toHaveBeenCalledTimes(1);
        });
    });

    describe('cleanup', () => {
        it('cleans up SSE replay stream', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok(createMockReplayResponse());

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);
            await vi.waitFor(() => expect(replay.signal).toBeDefined());

            expect(replay.signal?.aborted).toBe(false);

            store.cleanup();

            expect(replay.signal?.aborted).toBe(true);
        });
    });
});
