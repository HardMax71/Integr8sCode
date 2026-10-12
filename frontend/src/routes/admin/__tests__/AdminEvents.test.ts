import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { mockWindowGlobals, user, selectOption, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import {
    browseEventsApiV1AdminEventsBrowsePost,
    getEventStatsApiV1AdminEventsStatsGet,
    getEventDetailApiV1AdminEventsEventIdGet,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    replayEventsApiV1AdminEventsReplayPost,
    deleteEventApiV1AdminEventsEventIdDelete,
    getUserOverviewApiV1AdminUsersUserIdOverviewGet,
    ReplayStatus,
    type EventBrowseResponse,
    type EventReplayStatusResponse,
} from '#lib/api/index.ts';
import {
    fakeAdminUserOverview,
    fakeEventDetailResponse,
    fakeEventMetadata,
    fakeEventReplayResponse,
    fakeEventReplayStatusResponse,
    fakeEventStatsResponse,
    fakeEventSummary,
    fakeExecutionCompletedEvent,
    fakeExecutionFailedEvent,
    fakeExecutionStartedEvent,
    fakeUserResponse,
} from '#lib/api/@faker-js/faker.gen.ts';
import { toast } from 'svelte-sonner';

const mocks = vi.hoisted(() => ({
    windowOpen: vi.fn(),
    windowConfirm: vi.fn(),
}));

import AdminEvents from '#routes/admin/events/+page.svelte';

// The replay status stream sends these statuses, then the server closes it
function mockReplayStream(...statuses: EventReplayStatusResponse[]): void {
    vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).mockImplementation(async () => ({
        stream: (async function* () {
            yield* statuses;
        })(),
    }));
}

async function renderWithEvents(
    events: EventBrowseResponse['events'] = Array.from({ length: 5 }, () => fakeExecutionCompletedEvent()),
    stats = fakeEventStatsResponse(),
) {
    mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({ events, total: events.length, skip: 0, limit: 10 });
    mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(stats);

    const result = renderWithQueryClient(AdminEvents);
    await waitFor(() => expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalled());
    return result;
}

describe('AdminEvents', () => {
    beforeEach(() => {
        vi.unstubAllGlobals();
        mockWindowGlobals(mocks.windowOpen, mocks.windowConfirm);
        vi.clearAllMocks();
        mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({ events: [], total: 0, skip: 0, limit: 10 });
        mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(fakeEventStatsResponse());
        mockReplayStream();
        mocks.windowConfirm.mockReturnValue(true);
    });

    describe('initial loading', () => {
        it('calls loadEvents and loadStats on mount', async () => {
            renderWithQueryClient(AdminEvents);
            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledTimes(1);
                expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledTimes(1);
            });
        });

        it('sets up auto-refresh interval', async () => {
            renderWithQueryClient(AdminEvents);
            await tick();

            // Fast-forward 30 seconds
            await vi.advanceTimersByTimeAsync(30000);

            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledTimes(2);
                expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledTimes(2);
            });
        });

        it('shows the empty state when the events fail to load', async () => {
            mockApi(browseEventsApiV1AdminEventsBrowsePost).err({ detail: 'Network error' });
            renderWithQueryClient(AdminEvents);
            expect(await screen.findByText(/No events found/i)).toBeInTheDocument();
        });

        it('displays empty state when no events', async () => {
            await renderWithEvents([], { ...fakeEventStatsResponse(), total_events: 0 });
            expect(screen.getByText(/No events found/i)).toBeInTheDocument();
        });
    });

    describe('stats display', () => {
        it('displays event statistics cards', async () => {
            await renderWithEvents(
                Array.from({ length: 5 }, () => fakeExecutionCompletedEvent()),
                { ...fakeEventStatsResponse(), total_events: 150, error_rate: 2.5, avg_processing_time: 1.23 },
            );
            expect(screen.getByText('Total Events')).toBeInTheDocument();
            expect(screen.getByText('150')).toBeInTheDocument();
            expect(screen.getByText('2.5%')).toBeInTheDocument();
            expect(screen.getByText('1.23s')).toBeInTheDocument();
        });

        it('shows error rate in red when > 0', async () => {
            await renderWithEvents([fakeExecutionCompletedEvent()], { ...fakeEventStatsResponse(), error_rate: 5 });
            const errorRateElement = screen.getByText('5%');
            expect(errorRateElement).toHaveClass('text-red-600');
        });

        it('shows error rate in green when 0', async () => {
            await renderWithEvents([fakeExecutionCompletedEvent()], { ...fakeEventStatsResponse(), error_rate: 0 });
            const errorRateElement = screen.getByText('0%');
            expect(errorRateElement).toHaveClass('text-green-600');
        });
    });

    describe('event list rendering', () => {
        it('displays events in table', async () => {
            const events = [
                {
                    ...fakeExecutionCompletedEvent(),
                    metadata: { ...fakeEventMetadata(), user_id: 'user-1', service_name: 'test-service' },
                },
            ];
            await renderWithEvents(events);
            // Events are displayed (multiple due to mobile + desktop views)
            expect(screen.getAllByText('test-service')).toHaveLength(2);
        });

        it('displays multiple events', async () => {
            const events = Array.from({ length: 5 }, () => fakeExecutionCompletedEvent());
            await renderWithEvents(events);
            // Should show events info in pagination
            expect(screen.getByText(/Showing 1 - 5 of 5/i)).toBeInTheDocument();
        });

        it('shows user ID as clickable link', async () => {
            const events = [
                { ...fakeExecutionCompletedEvent(), metadata: { ...fakeEventMetadata(), user_id: 'user-123' } },
            ];
            await renderWithEvents(events);
            const userLinks = screen.getAllByText('user-123');
            expect(userLinks.length).toBeGreaterThan(0);
            // Verify at least one of the user links is a button (clickable)
            const hasButtonLink = userLinks.some((link) => link.tagName.toLowerCase() === 'button');
            expect(hasButtonLink).toBe(true);
        });
    });

    describe('refresh functionality', () => {
        it('refresh button reloads events', async () => {
            await renderWithEvents();
            vi.mocked(browseEventsApiV1AdminEventsBrowsePost).mockClear();

            const refreshBtn = screen.getByRole('button', { name: /Refresh/i });
            await user.click(refreshBtn);

            await waitFor(() => expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalled());
        });
    });

    describe('filters', () => {
        it('toggles filter panel', async () => {
            await renderWithEvents();

            const filtersBtn = screen.getByRole('button', { name: /Filters/i });
            await user.click(filtersBtn);

            await waitFor(() => {
                expect(screen.getByText(/Filter Events/i)).toBeInTheDocument();
                expect(screen.getByLabelText('Event Types')).toBeInTheDocument();
            });
        });

        it('displays filter inputs when panel is open', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Filters/i }));

            await waitFor(() => {
                expect(screen.getByLabelText('Search Text')).toBeInTheDocument();
                expect(screen.getByLabelText('Aggregate Id')).toBeInTheDocument();
                expect(screen.getByLabelText('User Id')).toBeInTheDocument();
                expect(screen.getByLabelText('Service Name')).toBeInTheDocument();
                expect(screen.getByLabelText(/Start Time/i)).toBeInTheDocument();
                expect(screen.getByLabelText(/End Time/i)).toBeInTheDocument();
            });
        });

        it('applies filters when Apply button is clicked', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Filters/i }));
            await waitFor(() => expect(screen.getByLabelText('Search Text')).toBeInTheDocument());

            await user.type(screen.getByLabelText('Search Text'), 'test query');
            vi.mocked(browseEventsApiV1AdminEventsBrowsePost).mockClear();

            await user.click(screen.getByRole('button', { name: /^Apply$/i }));

            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: expect.objectContaining({
                            filters: expect.objectContaining({
                                search_text: 'test query',
                            }),
                        }),
                    }),
                );
            });
        });

        it('clears all filters', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Filters/i }));
            await waitFor(() => expect(screen.getByLabelText('Search Text')).toBeInTheDocument());

            await user.type(screen.getByLabelText('Search Text'), 'test');
            await user.click(screen.getByRole('button', { name: /Clear All/i }));

            expect(screen.getByLabelText('Search Text')).toHaveValue('');
        });

        it('shows active filter count badge', async () => {
            await renderWithEvents(undefined, { ...fakeEventStatsResponse(), top_users: [] });

            await user.click(screen.getByRole('button', { name: /Filters/i }));
            await waitFor(() => expect(screen.getByLabelText('Search Text')).toBeInTheDocument());

            await user.type(screen.getByLabelText('Search Text'), 'test');
            await user.type(screen.getByLabelText('User Id'), 'user-1');
            await user.click(screen.getByRole('button', { name: /Apply/i }));

            // Close filters to see the badge, which counts the applied filters
            await user.click(screen.getByRole('button', { name: /Filters/i }));

            await waitFor(() => {
                const badge = screen.getByText('2');
                expect(badge).toBeInTheDocument();
            });
        });
    });

    describe('pagination', () => {
        it('shows pagination info', async () => {
            const events = Array.from({ length: 25 }, () => fakeExecutionCompletedEvent());
            mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({
                events: events.slice(0, 10),
                total: 25,
                skip: 0,
                limit: 10,
            });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(fakeEventStatsResponse());

            renderWithQueryClient(AdminEvents);
            await waitFor(() => expect(screen.getByText(/Showing 1 - 10 of 25/i)).toBeInTheDocument());
        });

        it('changes page when next is clicked', async () => {
            mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({
                events: Array.from({ length: 10 }, () => fakeExecutionCompletedEvent()),
                total: 25,
                skip: 0,
                limit: 10,
            });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(fakeEventStatsResponse());

            renderWithQueryClient(AdminEvents);
            const nextBtn = await waitFor(() => screen.getByLabelText('Next page'));

            vi.mocked(browseEventsApiV1AdminEventsBrowsePost).mockClear();
            await user.click(nextBtn);

            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: expect.objectContaining({
                            skip: 10,
                        }),
                    }),
                );
            });
        });

        it('changes page size', async () => {
            mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({
                events: Array.from({ length: 10 }, () => fakeExecutionCompletedEvent()),
                total: 50,
                skip: 0,
                limit: 10,
            });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(fakeEventStatsResponse());

            renderWithQueryClient(AdminEvents);
            const pageSizeSelect = await waitFor(() => screen.getByLabelText(/Items per page/i));

            vi.mocked(browseEventsApiV1AdminEventsBrowsePost).mockClear();
            selectOption(pageSizeSelect, '25');

            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: expect.objectContaining({
                            limit: 25,
                        }),
                    }),
                );
            });
        });
    });

    describe('event detail modal', () => {
        it('opens event detail modal when row is clicked', async () => {
            const event = { ...fakeExecutionCompletedEvent(), event_id: 'evt-detail-1' };
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok({ ...fakeEventDetailResponse(), event });
            await renderWithEvents([event]);

            // Multiple view detail buttons may exist (mobile + desktop views)
            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => {
                expect(vi.mocked(getEventDetailApiV1AdminEventsEventIdGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { event_id: 'evt-detail-1' },
                    }),
                );
                expect(screen.getByText(/Event Details/i)).toBeInTheDocument();
            });
        });

        it('displays event information in modal', async () => {
            const event = { ...fakeExecutionCompletedEvent(), event_id: 'evt-123' };
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok({ ...fakeEventDetailResponse(), event });
            await renderWithEvents([event]);

            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => {
                // Using getAllByText because values may appear in table + modal
                expect(screen.getAllByText('evt-123').length).toBeGreaterThan(0);
                expect(screen.getAllByText('execution_completed').length).toBeGreaterThan(0);
            });
        });

        it('shows related events in modal', async () => {
            const event = fakeExecutionCompletedEvent();
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok({
                ...fakeEventDetailResponse(),
                event,
                related_events: [
                    { ...fakeEventSummary(), event_type: 'execution_started' },
                    { ...fakeEventSummary(), event_type: 'pod_created' },
                ],
            });
            await renderWithEvents([event]);

            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => {
                expect(screen.getByText(/Related Events/i)).toBeInTheDocument();
                expect(screen.getByText('execution_started')).toBeInTheDocument();
                expect(screen.getByText('pod_created')).toBeInTheDocument();
            });
        });

        it('has close button in modal', async () => {
            const event = fakeExecutionCompletedEvent();
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok({ ...fakeEventDetailResponse(), event });
            await renderWithEvents([event]);

            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            const dialog = screen.getByRole('dialog');
            expect(within(dialog).getByRole('button', { name: 'Close dialog' })).toBeInTheDocument();
            expect(within(dialog).getByRole('button', { name: 'Close' })).toBeInTheDocument();
        });
    });

    describe('replay functionality', () => {
        it('shows replay preview on dry run', async () => {
            const events = [{ ...fakeExecutionCompletedEvent(), event_id: 'evt-replay-1' }];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                ...fakeEventReplayResponse(),
                dry_run: true,
                total_events: 1,
                replay_id: '',
                session_id: null,
                status: ReplayStatus.PREVIEW,
                events_preview: events,
            });
            await renderWithEvents(events);

            const [previewBtn] = screen.getAllByTitle('Preview replay');
            await user.click(previewBtn!);

            await waitFor(() => {
                expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: { event_ids: ['evt-replay-1'], dry_run: true },
                    }),
                );
                expect(screen.getByText(/Replay Preview/i)).toBeInTheDocument();
            });
        });

        it('confirms before actual replay', async () => {
            const events = [{ ...fakeExecutionCompletedEvent(), event_id: 'evt-replay-2' }];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({ ...fakeEventReplayResponse(), total_events: 1 });
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            expect(mocks.windowConfirm).toHaveBeenCalled();
            await waitFor(() => {
                expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: { event_ids: ['evt-replay-2'], dry_run: false },
                    }),
                );
            });
        });

        it('does not replay if confirm is cancelled', async () => {
            mocks.windowConfirm.mockReturnValue(false);
            const events = [fakeExecutionCompletedEvent()];
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).not.toHaveBeenCalled();
        });

        it('shows replay progress when session is active', async () => {
            const events = [{ ...fakeExecutionCompletedEvent(), event_id: 'evt-progress' }];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                ...fakeEventReplayResponse(),
                session_id: 'session-progress',
            });
            mockReplayStream({
                ...fakeEventReplayStatusResponse(),
                session_id: 'session-progress',
                status: ReplayStatus.RUNNING,
                replayed_events: 2,
                progress_percentage: 40,
            });
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            await waitFor(() => {
                expect(screen.getByText(/Replay in Progress/i)).toBeInTheDocument();
            });
        });
    });

    describe('delete event', () => {
        it('confirms before deleting', async () => {
            const events = [{ ...fakeExecutionCompletedEvent(), event_id: 'evt-delete-1' }];
            mockApi(deleteEventApiV1AdminEventsEventIdDelete).ok({ message: 'Event deleted', event_id: 'evt-1' });
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            expect(mocks.windowConfirm).toHaveBeenCalled();
            await waitFor(() => {
                expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { event_id: 'evt-delete-1' },
                    }),
                );
            });
        });

        it('shows success toast after deletion', async () => {
            const events = [fakeExecutionCompletedEvent()];
            mockApi(deleteEventApiV1AdminEventsEventIdDelete).ok({ message: 'Event deleted', event_id: 'evt-1' });
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            await waitFor(() => {
                expect(vi.mocked(toast.success)).toHaveBeenCalledWith('Event deleted successfully');
            });
        });

        it('does not delete if confirm is cancelled', async () => {
            mocks.windowConfirm.mockReturnValue(false);
            const events = [fakeExecutionCompletedEvent()];
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).not.toHaveBeenCalled();
        });

        it('reports no success when the delete fails', async () => {
            mockApi(deleteEventApiV1AdminEventsEventIdDelete).err({ detail: 'Cannot delete' });
            const events = [fakeExecutionCompletedEvent()];
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            await waitFor(() => expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).toHaveBeenCalled());
            expect(vi.mocked(toast.success)).not.toHaveBeenCalledWith('Event deleted successfully');
        });
    });

    describe('export', () => {
        it('opens export dropdown menu', async () => {
            await renderWithEvents();

            const exportBtn = screen.getByRole('button', { name: /Export/i });
            await user.click(exportBtn);

            await waitFor(() => {
                expect(screen.getByText('Export as csv')).toBeInTheDocument();
                expect(screen.getByText('Export as json')).toBeInTheDocument();
            });
        });

        it('exports as CSV', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Export/i }));
            await waitFor(() => expect(screen.getByText('Export as csv')).toBeInTheDocument());

            await user.click(screen.getByText('Export as csv'));

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/csv'),
                '_blank',
            );
            expect(vi.mocked(toast.info)).toHaveBeenCalledWith(expect.stringContaining('Starting csv export'));
        });

        it('exports as JSON', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Export/i }));
            await waitFor(() => expect(screen.getByText('Export as json')).toBeInTheDocument());

            await user.click(screen.getByText('Export as json'));

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/json'),
                '_blank',
            );
            expect(vi.mocked(toast.info)).toHaveBeenCalledWith(expect.stringContaining('Starting json export'));
        });
    });

    describe('user overview modal', () => {
        it('opens user overview modal when user ID is clicked', async () => {
            const events = [
                { ...fakeExecutionCompletedEvent(), metadata: { ...fakeEventMetadata(), user_id: 'user-overview-1' } },
            ];
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(fakeAdminUserOverview());
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-overview-1');
            await user.click(userLink!);

            await waitFor(() => {
                expect(vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'user-overview-1' },
                    }),
                );
                expect(screen.getByText(/User Overview/i)).toBeInTheDocument();
            });
        });

        it('displays user information in overview modal', async () => {
            const events = [
                { ...fakeExecutionCompletedEvent(), metadata: { ...fakeEventMetadata(), user_id: 'user-info' } },
            ];
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok({
                ...fakeAdminUserOverview(),
                user: { ...fakeUserResponse(), username: 'testuser', email: 'test@example.com' },
            });
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-info');
            await user.click(userLink!);

            await waitFor(() => {
                expect(screen.getByText('testuser')).toBeInTheDocument();
                expect(screen.getByText('test@example.com')).toBeInTheDocument();
            });
        });

        it('shows execution stats in overview modal', async () => {
            const events = [
                { ...fakeExecutionCompletedEvent(), metadata: { ...fakeEventMetadata(), user_id: 'user-stats' } },
            ];
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok({
                ...fakeAdminUserOverview(),
                derived_counts: { succeeded: 80, failed: 10, timeout: 5, cancelled: 5, terminal_total: 100 },
            });
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-stats');
            await user.click(userLink!);

            await waitFor(() => {
                // Using getAllByText because values may appear in table + modal + page controls
                expect(screen.getAllByText('Succeeded').length).toBeGreaterThan(0);
                expect(screen.getAllByText('80').length).toBeGreaterThan(0);
                expect(screen.getAllByText('Failed').length).toBeGreaterThan(0);
                expect(screen.getAllByText('10').length).toBeGreaterThan(0);
            });
        });

        it('shows no data in the overview when it fails to load', async () => {
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).err({ detail: 'Failed to load' });
            const events = [
                { ...fakeExecutionCompletedEvent(), metadata: { ...fakeEventMetadata(), user_id: 'user-error' } },
            ];
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-error');
            await user.click(userLink!);

            expect(await screen.findByText('No data available')).toBeInTheDocument();
        });
    });

    describe('event type display', () => {
        it('shows correct color for completed events', async () => {
            const events = [fakeExecutionCompletedEvent()];
            await renderWithEvents(events);
            const [icon] = screen.getAllByTestId('event-type-icon');
            expect(icon).toHaveAttribute('data-event-type', 'execution_completed');
            expect(icon).toHaveClass('text-green-600');
        });

        it('shows correct color for failed events', async () => {
            const events = [fakeExecutionFailedEvent()];
            await renderWithEvents(events);
            const [icon] = screen.getAllByTestId('event-type-icon');
            expect(icon).toHaveAttribute('data-event-type', 'execution_failed');
            expect(icon).toHaveClass('text-red-600');
        });

        it('shows correct color for started events', async () => {
            const events = [fakeExecutionStartedEvent()];
            await renderWithEvents(events);
            const [icon] = screen.getAllByTestId('event-type-icon');
            expect(icon).toHaveAttribute('data-event-type', 'execution_started');
            expect(icon).toHaveClass('text-blue-600');
        });
    });

    describe('header and layout', () => {
        it('displays page title', async () => {
            await renderWithEvents();
            expect(screen.getByText('Event Browser')).toBeInTheDocument();
        });

        it('has Filters, Export, and Refresh buttons', async () => {
            await renderWithEvents();
            expect(screen.getByRole('button', { name: /Filters/i })).toBeInTheDocument();
            expect(screen.getByRole('button', { name: /Export/i })).toBeInTheDocument();
            expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
        });
    });

    describe('error handling', () => {
        it('opens no details when the event fails to load', async () => {
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).err({ detail: 'Detail not found' });
            const events = [fakeExecutionCompletedEvent()];
            await renderWithEvents(events);

            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => expect(vi.mocked(getEventDetailApiV1AdminEventsEventIdGet)).toHaveBeenCalled());
            expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        });

        it('starts no progress tracking when the replay fails', async () => {
            mockApi(replayEventsApiV1AdminEventsReplayPost).err({ detail: 'Replay failed' });
            const events = [fakeExecutionCompletedEvent()];
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            await waitFor(() => expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).toHaveBeenCalled());
            expect(vi.mocked(toast.success)).not.toHaveBeenCalled();
            expect(vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet)).not.toHaveBeenCalled();
        });
    });
});
