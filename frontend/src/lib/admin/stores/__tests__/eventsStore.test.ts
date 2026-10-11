import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { createInQueryContext, createMockEvent, createMockStats, mockApi } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import {
    browseEventsApiV1AdminEventsBrowsePost,
    getEventStatsApiV1AdminEventsStatsGet,
    getEventDetailApiV1AdminEventsEventIdGet,
    replayEventsApiV1AdminEventsReplayPost,
    deleteEventApiV1AdminEventsEventIdDelete,
    getUserOverviewApiV1AdminUsersUserIdOverviewGet,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    type EventReplayStatusResponse,
} from '#lib/api/index.ts';
import { createEventsStore } from '#lib/admin/stores/eventsStore.svelte.ts';

const windowOpen = vi.fn();
const windowConfirm = vi.fn();

// Stands in for the generated SSE call: tests push status updates, and aborting ends the stream like the real client
function mockReplayStream() {
    const pending: EventReplayStatusResponse[] = [];
    let wake: (() => void) | null = null;
    let signal: AbortSignal | undefined;

    async function* stream(): AsyncGenerator<EventReplayStatusResponse> {
        while (!signal?.aborted) {
            const next = pending.shift();
            if (next) {
                yield next;
                continue;
            }
            await new Promise<void>((resolve) => (wake = resolve));
        }
    }

    vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).mockImplementation(async (options) => {
        signal = options.signal ?? undefined;
        signal?.addEventListener('abort', () => wake?.());
        return { stream: stream() } as never;
    });

    return {
        push(status: Partial<EventReplayStatusResponse>): void {
            pending.push({
                session_id: 'session-1',
                replay_id: 'replay-1',
                errors: [],
                ...status,
            } as EventReplayStatusResponse);
            wake?.();
            wake = null;
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
            expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledWith(
                expect.objectContaining({ query: { hours: 24 } }),
            );
        });

        it('sends the page as skip and limit', async () => {
            createStore();
            store.currentPage = 2;

            await vi.waitFor(() => expect(lastBrowseBody()).toMatchObject({ skip: 10, limit: 10 }));
        });

        it('sends the filters only once they are applied, with times as ISO strings', async () => {
            createStore();
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(1));
            store.currentPage = 2;
            await vi.waitFor(() => expect(browseEvents).toHaveBeenCalledTimes(2));

            store.filters = { user_id: 'user-1', aggregate_id: 'agg-1', start_time: '2026-01-02T03:04' };
            await vi.advanceTimersByTimeAsync(100);
            expect(browseEvents).toHaveBeenCalledTimes(2);

            store.applyFilters();

            expect(store.currentPage).toBe(1);
            await vi.waitFor(() =>
                expect(lastBrowseBody()).toEqual({
                    filters: {
                        user_id: 'user-1',
                        aggregate_id: 'agg-1',
                        start_time: new Date('2026-01-02T03:04').toISOString(),
                        end_time: null,
                    },
                    skip: 0,
                    limit: 10,
                }),
            );
        });
    });

    describe('openEventDetail', () => {
        it('loads the event into selectedEvent', async () => {
            const detail = { event: createMockEvent(), related_events: [], timeline: [] };
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
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                total_events: 1,
                events_preview: preview,
            });

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

        it('confirms and starts SSE stream for actual replay', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                total_events: 1,
                session_id: 'session-1',
                replay_id: 'replay-1',
            });

            mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);

            expect(windowConfirm).toHaveBeenCalled();
            await vi.waitFor(() =>
                expect(vi.mocked(toast.success)).toHaveBeenCalledWith(expect.stringContaining('Replay scheduled')),
            );
            expect(store.activeReplaySession).toBeTruthy();
            expect(vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { session_id: 'session-1' } }),
            );
        });

        it('updates activeReplaySession from SSE messages', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                total_events: 5,
                session_id: 'session-1',
                replay_id: 'replay-1',
            });

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);
            await vi.waitFor(() => expect(store.activeReplaySession).toBeTruthy());

            replay.push({
                status: 'running',
                total_events: 5,
                replayed_events: 3,
                failed_events: 0,
                skipped_events: 0,
            });

            await vi.waitFor(() => expect(store.activeReplaySession?.replayed_events).toBe(3));
            expect(store.activeReplaySession?.progress_percentage).toBe(60);
        });

        it('disconnects SSE on terminal status', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                total_events: 5,
                session_id: 'session-1',
                replay_id: 'replay-1',
            });

            const replay = mockReplayStream();
            createStore();
            store.replayEvent('evt-1', false);
            await vi.waitFor(() => expect(store.activeReplaySession).toBeTruthy());

            replay.push({
                status: 'completed',
                total_events: 5,
                replayed_events: 5,
                failed_events: 0,
                skipped_events: 0,
            });

            await vi.waitFor(() =>
                expect(vi.mocked(toast.success)).toHaveBeenCalledWith(expect.stringContaining('Replay completed')),
            );
            expect(replay.signal?.aborted).toBe(true);
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
            expect(vi.mocked(toast.info)).toHaveBeenCalledWith(expect.stringContaining('CSV'));
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

        it('sends each event type as its own query parameter, as the API expects', () => {
            createStore();
            store.filters = { event_types: ['execution_requested', 'pod_created'] };
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
            const overview = { user: { user_id: 'user-1' }, stats: {}, derived_counts: {} };
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
            store.currentPage = 3;

            store.clearFilters();

            expect(store.filters).toEqual({});
            expect(store.appliedFilters).toEqual({});
            expect(store.currentPage).toBe(1);
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
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                total_events: 1,
                session_id: 'session-1',
                replay_id: 'replay-1',
            });

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
