import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { effect_root } from 'svelte/internal/client';
import { createMockEvent, createMockStats } from '$test/test-utils';

const mocks = vi.hoisted(() => ({
    browseEventsApiV1AdminEventsBrowsePost: vi.fn(),
    getEventStatsApiV1AdminEventsStatsGet: vi.fn(),
    getEventDetailApiV1AdminEventsEventIdGet: vi.fn(),
    replayEventsApiV1AdminEventsReplayPost: vi.fn(),
    deleteEventApiV1AdminEventsEventIdDelete: vi.fn(),
    getUserOverviewApiV1AdminUsersUserIdOverviewGet: vi.fn(),
    unwrap: vi.fn((result: { data: unknown }) => result?.data),
    unwrapOr: vi.fn((result: { data: unknown }, fallback: unknown) => result?.data ?? fallback),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    toastInfo: vi.fn(),
    windowOpen: vi.fn(),
    windowConfirm: vi.fn(),
}));

vi.mock('$lib/api', () => ({
    browseEventsApiV1AdminEventsBrowsePost: (...args: unknown[]) => mocks.browseEventsApiV1AdminEventsBrowsePost(...args),
    getEventStatsApiV1AdminEventsStatsGet: (...args: unknown[]) => mocks.getEventStatsApiV1AdminEventsStatsGet(...args),
    getEventDetailApiV1AdminEventsEventIdGet: (...args: unknown[]) => mocks.getEventDetailApiV1AdminEventsEventIdGet(...args),
    replayEventsApiV1AdminEventsReplayPost: (...args: unknown[]) => mocks.replayEventsApiV1AdminEventsReplayPost(...args),
    deleteEventApiV1AdminEventsEventIdDelete: (...args: unknown[]) => mocks.deleteEventApiV1AdminEventsEventIdDelete(...args),
    getUserOverviewApiV1AdminUsersUserIdOverviewGet: (...args: unknown[]) => mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet(...args),
}));

vi.mock('$lib/api-interceptors', () => ({
    unwrap: (result: { data: unknown }) => mocks.unwrap(result),
    unwrapOr: (result: { data: unknown }, fallback: unknown) => mocks.unwrapOr(result, fallback),
}));

vi.mock('svelte-sonner', () => ({
    toast: {
        success: (...args: unknown[]) => mocks.toastSuccess(...args),
        error: (...args: unknown[]) => mocks.toastError(...args),
        info: (...args: unknown[]) => mocks.toastInfo(...args),
        warning: vi.fn(),
    },
}));

type EventSourceHandler = ((event: MessageEvent) => void) | null;

class MockEventSource {
    url: string;
    onmessage: EventSourceHandler = null;
    onerror: ((event: Event) => void) | null = null;
    closed = false;
    static instances: MockEventSource[] = [];

    constructor(url: string) {
        this.url = url;
        MockEventSource.instances.push(this);
    }

    close(): void {
        this.closed = true;
    }

    simulateMessage(data: string): void {
        if (this.onmessage) {
            this.onmessage(new MessageEvent('message', { data }));
        }
    }

    simulateError(): void {
        if (this.onerror) {
            this.onerror(new Event('error'));
        }
    }
}

const { createEventsStore } = await import('../eventsStore.svelte');

describe('EventsStore', () => {
    let store: ReturnType<typeof createEventsStore>;
    let teardown: () => void;

    beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: false });
        vi.clearAllMocks();
        MockEventSource.instances = [];
        vi.stubGlobal('EventSource', MockEventSource);
        vi.stubGlobal('open', mocks.windowOpen);
        vi.stubGlobal('confirm', mocks.windowConfirm);
        mocks.windowConfirm.mockReturnValue(true);
        mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({
            data: { events: [], total: 0 },
        });
        mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({
            data: null,
        });
    });

    function createStore() {
        teardown = effect_root(() => {
            store = createEventsStore();
        });
    }

    afterEach(() => {
        vi.unstubAllGlobals();
        store?.cleanup();
        teardown?.();
    });

    describe('initial state', () => {
        it('starts with empty data', () => {
            createStore();
            expect(store.events).toEqual([]);
            expect(store.totalEvents).toBe(0);
            expect(store.loading).toBe(false);
            expect(store.stats).toBeNull();
            expect(store.filters).toEqual({});
        });
    });

    describe('loadAll', () => {
        it('loads events and stats', async () => {
            const events = [createMockEvent()];
            const stats = createMockStats();
            mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({
                data: { events, total: 1 },
            });
            mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({
                data: stats,
            });

            createStore();
            await store.loadAll();

            expect(store.events).toEqual(events);
            expect(store.totalEvents).toBe(1);
            expect(store.stats).toEqual(stats);
        });
    });

    describe('loadEvents', () => {
        it('passes pagination to API', async () => {
            createStore();
            store.pagination.currentPage = 2;
            await store.loadEvents();

            expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledWith(
                expect.objectContaining({
                    body: expect.objectContaining({ skip: 10, limit: 10 }),
                }),
            );
        });

        it('passes filters to API', async () => {
            createStore();
            store.filters = { user_id: 'user-1', aggregate_id: 'agg-1' };
            await store.loadEvents();

            expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledWith(
                expect.objectContaining({
                    body: expect.objectContaining({
                        filters: expect.objectContaining({
                            user_id: 'user-1',
                            aggregate_id: 'agg-1',
                        }),
                    }),
                }),
            );
        });

        it('handles empty response', async () => {
            mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({ data: null });

            createStore();
            await store.loadEvents();

            expect(store.events).toEqual([]);
            expect(store.totalEvents).toBe(0);
        });
    });

    describe('loadEventDetail', () => {
        it('returns event detail', async () => {
            const detail = { event: createMockEvent(), related_events: [], timeline: [] };
            mocks.getEventDetailApiV1AdminEventsEventIdGet.mockResolvedValue({ data: detail });

            createStore();
            const result = await store.loadEventDetail('evt-1');

            expect(result).toEqual(detail);
            expect(mocks.getEventDetailApiV1AdminEventsEventIdGet).toHaveBeenCalledWith({
                path: { event_id: 'evt-1' },
            });
        });
    });

    describe('replayEvent', () => {
        it('performs dry run and sets replayPreview', async () => {
            const preview = [createMockEvent()];
            mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
                data: { total_events: 1, events_preview: preview },
            });

            createStore();
            await store.replayEvent('evt-1', true);

            expect(store.replayPreview).toEqual({
                eventId: 'evt-1',
                total_events: 1,
                events_preview: preview,
            });
        });

        it('confirms and starts SSE stream for actual replay', async () => {
            mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
                data: { total_events: 1, session_id: 'session-1', replay_id: 'replay-1' },
            });

            createStore();
            await store.replayEvent('evt-1', false);

            expect(mocks.windowConfirm).toHaveBeenCalled();
            expect(mocks.toastSuccess).toHaveBeenCalledWith(expect.stringContaining('Replay scheduled'));
            expect(store.activeReplaySession).toBeTruthy();
            expect(MockEventSource.instances).toHaveLength(1);
            expect(MockEventSource.instances[0]!.url).toBe('/api/v1/admin/events/replay/session-1/status');
        });

        it('updates activeReplaySession from SSE messages', async () => {
            mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
                data: { total_events: 5, session_id: 'session-1', replay_id: 'replay-1' },
            });

            createStore();
            await store.replayEvent('evt-1', false);

            const es = MockEventSource.instances[0]!;
            es.simulateMessage(JSON.stringify({
                session_id: 'session-1',
                status: 'running',
                total_events: 5,
                replayed_events: 3,
                failed_events: 0,
                skipped_events: 0,
                replay_id: 'replay-1',
                created_at: '2024-01-01T00:00:00Z',
                errors: [],
            }));

            expect(store.activeReplaySession?.replayed_events).toBe(3);
            expect(store.activeReplaySession?.progress_percentage).toBe(60);
        });

        it('disconnects SSE on terminal status', async () => {
            mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
                data: { total_events: 5, session_id: 'session-1', replay_id: 'replay-1' },
            });

            createStore();
            await store.replayEvent('evt-1', false);

            const es = MockEventSource.instances[0]!;
            es.simulateMessage(JSON.stringify({
                session_id: 'session-1',
                status: 'completed',
                total_events: 5,
                replayed_events: 5,
                failed_events: 0,
                skipped_events: 0,
                replay_id: 'replay-1',
                created_at: '2024-01-01T00:00:00Z',
                errors: [],
            }));

            expect(mocks.toastSuccess).toHaveBeenCalledWith(expect.stringContaining('Replay completed'));
            expect(es.closed).toBe(true);
        });

        it('does not replay if confirm is cancelled', async () => {
            mocks.windowConfirm.mockReturnValue(false);

            createStore();
            await store.replayEvent('evt-1', false);

            expect(mocks.replayEventsApiV1AdminEventsReplayPost).not.toHaveBeenCalled();
        });
    });

    describe('deleteEvent', () => {
        it('confirms and deletes event', async () => {
            mocks.deleteEventApiV1AdminEventsEventIdDelete.mockResolvedValue({ data: {} });

            createStore();
            await store.deleteEvent('evt-1');

            expect(mocks.windowConfirm).toHaveBeenCalled();
            expect(mocks.deleteEventApiV1AdminEventsEventIdDelete).toHaveBeenCalledWith({
                path: { event_id: 'evt-1' },
            });
            expect(mocks.toastSuccess).toHaveBeenCalledWith('Event deleted successfully');
        });

        it('does not delete if confirm is cancelled', async () => {
            mocks.windowConfirm.mockReturnValue(false);

            createStore();
            await store.deleteEvent('evt-1');

            expect(mocks.deleteEventApiV1AdminEventsEventIdDelete).not.toHaveBeenCalled();
        });
    });

    describe('exportEvents', () => {
        it('opens export URL for CSV', () => {
            createStore();
            store.exportEvents('csv');

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/csv'),
                '_blank',
            );
            expect(mocks.toastInfo).toHaveBeenCalledWith(expect.stringContaining('CSV'));
        });

        it('opens export URL for JSON', () => {
            createStore();
            store.exportEvents('json');

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/json'),
                '_blank',
            );
        });

        it('includes filter params in export URL', () => {
            createStore();
            store.filters = { user_id: 'user-1', aggregate_id: 'agg-1' };
            store.exportEvents('csv');

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringMatching(/user_id=user-1/),
                '_blank',
            );
        });
    });

    describe('openUserOverview', () => {
        it('loads user overview', async () => {
            const overview = { user: { user_id: 'user-1' }, stats: {}, derived_counts: {} };
            mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet.mockResolvedValue({
                data: overview,
            });

            createStore();
            await store.openUserOverview('user-1');

            expect(store.userOverview).toEqual(overview);
            expect(store.userOverviewLoading).toBe(false);
        });

        it('skips empty userId', async () => {
            createStore();
            await store.openUserOverview('');

            expect(mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet).not.toHaveBeenCalled();
        });
    });

    describe('clearFilters', () => {
        it('resets filters and reloads', async () => {
            createStore();
            store.filters = { user_id: 'test' };
            store.pagination.currentPage = 3;

            store.clearFilters();

            expect(store.filters).toEqual({});
            expect(store.pagination.currentPage).toBe(1);
            expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled();
        });
    });

    describe('auto-refresh', () => {
        it('fires loadAll on 30s interval', async () => {
            createStore();
            vi.clearAllMocks();

            await vi.advanceTimersByTimeAsync(30000);
            expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledTimes(1);

            await vi.advanceTimersByTimeAsync(30000);
            expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledTimes(2);
        });

        it('stops on cleanup', async () => {
            createStore();
            await vi.advanceTimersByTimeAsync(30000);
            expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled();

            const callsBefore = mocks.browseEventsApiV1AdminEventsBrowsePost.mock.calls.length;
            store.mainRefresh.enabled = false;
            store.cleanup();

            await vi.advanceTimersByTimeAsync(60000);
            expect(mocks.browseEventsApiV1AdminEventsBrowsePost.mock.calls.length).toBe(callsBefore);
        });
    });

    describe('cleanup', () => {
        it('cleans up SSE replay stream', async () => {
            mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
                data: { total_events: 1, session_id: 'session-1', replay_id: 'replay-1' },
            });

            createStore();
            await store.replayEvent('evt-1', false);

            const es = MockEventSource.instances[0]!;
            expect(es.closed).toBe(false);

            store.cleanup();

            expect(es.closed).toBe(true);
        });
    });
});
