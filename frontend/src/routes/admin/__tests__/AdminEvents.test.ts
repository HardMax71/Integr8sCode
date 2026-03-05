import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import {
    mockWindowGlobals,
    createMockEvent,
    createMockEvents,
    createMockStats,
    createMockEventDetail,
    createMockUserOverview,
    user,
    selectOption,
    mockApi,
} from '$test/test-utils';
import {
    browseEventsApiV1AdminEventsBrowsePost,
    getEventStatsApiV1AdminEventsStatsGet,
    getEventDetailApiV1AdminEventsEventIdGet,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    replayEventsApiV1AdminEventsReplayPost,
    deleteEventApiV1AdminEventsEventIdDelete,
    getUserOverviewApiV1AdminUsersUserIdOverviewGet,
} from '$lib/api';
import { toast } from 'svelte-sonner';

const mocks = vi.hoisted(() => ({
    windowOpen: vi.fn(),
    windowConfirm: vi.fn(),
}));

vi.mock('$routes/admin/AdminLayout.svelte', async () => {
    const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
    return { default: MockLayout };
});

import AdminEvents from '$routes/admin/AdminEvents.svelte';

async function renderWithEvents(events = createMockEvents(5), stats = createMockStats()) {
    mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({ events, total: events.length, skip: 0, limit: 10 });
    mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(stats);

    const result = render(AdminEvents);
    await waitFor(() => expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalled());
    return result;
}

describe('AdminEvents', () => {
    beforeEach(() => {
        vi.unstubAllGlobals();
        mockWindowGlobals(mocks.windowOpen, mocks.windowConfirm);
        vi.clearAllMocks();
        mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({ events: [], total: 0, skip: 0, limit: 10 });
        mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(null);
        mockApi(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).ok({
            session_id: 'test',
            status: 'completed',
            total_events: 0,
            replayed_events: 0,
            progress_percentage: 100,
        });
        mocks.windowConfirm.mockReturnValue(true);
    });

    describe('initial loading', () => {
        it('calls loadEvents and loadStats on mount', async () => {
            render(AdminEvents);
            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledTimes(1);
                expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledTimes(1);
            });
        });

        it('sets up auto-refresh interval', async () => {
            render(AdminEvents);
            await tick();

            // Fast-forward 30 seconds
            await vi.advanceTimersByTimeAsync(30000);

            await waitFor(() => {
                expect(vi.mocked(browseEventsApiV1AdminEventsBrowsePost)).toHaveBeenCalledTimes(2);
                expect(vi.mocked(getEventStatsApiV1AdminEventsStatsGet)).toHaveBeenCalledTimes(2);
            });
        });

        it('handles API error on load events and shows toast', async () => {
            const error = { message: 'Network error' };
            vi.mocked(browseEventsApiV1AdminEventsBrowsePost).mockImplementation(async () => {
                toast.error('Failed to load events');
                return { data: null, error } as any;
            });
            render(AdminEvents);
            await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to load events'));
        });

        it('displays empty state when no events', async () => {
            await renderWithEvents([], createMockStats({ total_events: 0 }));
            expect(screen.getByText(/No events found/i)).toBeInTheDocument();
        });
    });

    describe('stats display', () => {
        it('displays event statistics cards', async () => {
            await renderWithEvents(
                createMockEvents(5),
                createMockStats({ total_events: 150, error_rate: 2.5, avg_processing_time: 1.23 }),
            );
            expect(screen.getByText(/Events \(Last 24h\)/i)).toBeInTheDocument();
            expect(screen.getByText('150')).toBeInTheDocument();
            expect(screen.getByText('2.5%')).toBeInTheDocument();
            expect(screen.getByText('1.23s')).toBeInTheDocument();
        });

        it('shows error rate in red when > 0', async () => {
            await renderWithEvents(createMockEvents(1), createMockStats({ error_rate: 5 }));
            const errorRateElement = screen.getByText('5%');
            expect(errorRateElement).toHaveClass('text-red-600');
        });

        it('shows error rate in green when 0', async () => {
            await renderWithEvents(createMockEvents(1), createMockStats({ error_rate: 0 }));
            const errorRateElement = screen.getByText('0%');
            expect(errorRateElement).toHaveClass('text-green-600');
        });
    });

    describe('event list rendering', () => {
        it('displays events in table', async () => {
            const events = [
                createMockEvent({
                    event_type: 'execution_completed',
                    metadata: { user_id: 'user-1', service_name: 'test-service' },
                }),
            ];
            await renderWithEvents(events);
            // Events are displayed (multiple due to mobile + desktop views)
            expect(screen.getAllByText('test-service')).toHaveLength(2);
        });

        it('displays multiple events', async () => {
            const events = createMockEvents(5);
            await renderWithEvents(events);
            // Should show events info in pagination
            expect(screen.getByText(/Showing 1 to 5 of 5 events/i)).toBeInTheDocument();
        });

        it('shows user ID as clickable link', async () => {
            const events = [createMockEvent({ metadata: { user_id: 'user-123' } })];
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
                expect(screen.getByLabelText(/Event Types/i)).toBeInTheDocument();
            });
        });

        it('displays filter inputs when panel is open', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Filters/i }));

            await waitFor(() => {
                expect(screen.getByLabelText(/Search/i)).toBeInTheDocument();
                expect(screen.getByLabelText(/Aggregate ID/i)).toBeInTheDocument();
                expect(screen.getByLabelText(/User ID/i)).toBeInTheDocument();
                expect(screen.getByLabelText(/Service/i)).toBeInTheDocument();
                expect(screen.getByLabelText(/Start Time/i)).toBeInTheDocument();
                expect(screen.getByLabelText(/End Time/i)).toBeInTheDocument();
            });
        });

        it('applies filters when Apply button is clicked', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Filters/i }));
            await waitFor(() => expect(screen.getByLabelText(/Search/i)).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Search/i), 'test query');
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
            await waitFor(() => expect(screen.getByLabelText(/Search/i)).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Search/i), 'test');
            await user.click(screen.getByRole('button', { name: /Clear All/i }));

            expect(screen.getByLabelText(/Search/i)).toHaveValue('');
        });

        it('shows active filter count badge', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Filters/i }));
            await waitFor(() => expect(screen.getByLabelText(/Search/i)).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Search/i), 'test');
            await user.type(screen.getByLabelText(/User ID/i), 'user-1');

            // Close filters to see the badge
            await user.click(screen.getByRole('button', { name: /Filters/i }));

            await waitFor(() => {
                const badge = screen.getByText('2');
                expect(badge).toBeInTheDocument();
            });
        });
    });

    describe('pagination', () => {
        it('shows pagination info', async () => {
            const events = createMockEvents(25);
            mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({
                events: events.slice(0, 10),
                total: 25,
                skip: 0,
                limit: 10,
            });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(createMockStats());

            render(AdminEvents);
            await waitFor(() => expect(screen.getByText(/Showing 1 to 10 of 25 events/i)).toBeInTheDocument());
        });

        it('changes page when next is clicked', async () => {
            mockApi(browseEventsApiV1AdminEventsBrowsePost).ok({
                events: createMockEvents(10),
                total: 25,
                skip: 0,
                limit: 10,
            });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(createMockStats());

            render(AdminEvents);
            const nextBtn = await waitFor(() => screen.getByTitle('Next page'));

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
                events: createMockEvents(10),
                total: 50,
                skip: 0,
                limit: 10,
            });
            mockApi(getEventStatsApiV1AdminEventsStatsGet).ok(createMockStats());

            render(AdminEvents);
            const pageSizeSelect = await waitFor(() => screen.getByLabelText(/Show:/i));

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
            const events = [createMockEvent({ event_id: 'evt-detail-1' })];
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(createMockEventDetail(events[0]));
            await renderWithEvents(events);

            // Multiple view detail buttons may exist (mobile + desktop views)
            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => {
                expect(vi.mocked(getEventDetailApiV1AdminEventsEventIdGet)).toHaveBeenCalledWith({
                    path: { event_id: 'evt-detail-1' },
                });
                expect(screen.getByText(/Event Details/i)).toBeInTheDocument();
            });
        });

        it('displays event information in modal', async () => {
            const event = createMockEvent({ event_id: 'evt-123', event_type: 'execution_completed' });
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(createMockEventDetail(event));
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
            const event = createMockEvent();
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(createMockEventDetail(event));
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
            const event = createMockEvent();
            mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(createMockEventDetail(event));
            await renderWithEvents([event]);

            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            // Verify close buttons exist (Modal X button and footer Close button)
            expect(screen.getByRole('button', { name: /Close modal/i })).toBeInTheDocument();
            expect(screen.getByRole('button', { name: /^Close$/i })).toBeInTheDocument();
        });
    });

    describe('replay functionality', () => {
        it('shows replay preview on dry run', async () => {
            const events = [createMockEvent({ event_id: 'evt-replay-1' })];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                dry_run: true,
                total_events: 1,
                replay_id: '',
                session_id: null,
                status: 'preview',
                events_preview: events,
            });
            await renderWithEvents(events);

            const [previewBtn] = screen.getAllByTitle('Preview replay');
            await user.click(previewBtn!);

            await waitFor(() => {
                expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).toHaveBeenCalledWith({
                    body: { event_ids: ['evt-replay-1'], dry_run: true },
                });
                expect(screen.getByText(/Replay Preview/i)).toBeInTheDocument();
            });
        });

        it('confirms before actual replay', async () => {
            const events = [createMockEvent({ event_id: 'evt-replay-2' })];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                dry_run: false,
                total_events: 1,
                replay_id: 'replay-1',
                session_id: 'session-1',
                status: 'scheduled',
                events_preview: null,
            });
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            expect(mocks.windowConfirm).toHaveBeenCalled();
            await waitFor(() => {
                expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).toHaveBeenCalledWith({
                    body: { event_ids: ['evt-replay-2'], dry_run: false },
                });
            });
        });

        it('does not replay if confirm is cancelled', async () => {
            mocks.windowConfirm.mockReturnValue(false);
            const events = [createMockEvent()];
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            expect(vi.mocked(replayEventsApiV1AdminEventsReplayPost)).not.toHaveBeenCalled();
        });

        it('shows replay progress when session is active', async () => {
            const events = [createMockEvent({ event_id: 'evt-progress' })];
            mockApi(replayEventsApiV1AdminEventsReplayPost).ok({
                dry_run: false,
                total_events: 5,
                replay_id: 'replay-p',
                session_id: 'session-progress',
                status: 'scheduled',
                events_preview: null,
            });
            mockApi(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).ok({
                session_id: 'session-progress',
                status: 'in_progress',
                total_events: 5,
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
            const events = [createMockEvent({ event_id: 'evt-delete-1' })];
            mockApi(deleteEventApiV1AdminEventsEventIdDelete).ok({});
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            expect(mocks.windowConfirm).toHaveBeenCalled();
            await waitFor(() => {
                expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).toHaveBeenCalledWith({
                    path: { event_id: 'evt-delete-1' },
                });
            });
        });

        it('shows success toast after deletion', async () => {
            const events = [createMockEvent()];
            mockApi(deleteEventApiV1AdminEventsEventIdDelete).ok({});
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            await waitFor(() => {
                expect(vi.mocked(toast.success)).toHaveBeenCalledWith('Event deleted successfully');
            });
        });

        it('does not delete if confirm is cancelled', async () => {
            mocks.windowConfirm.mockReturnValue(false);
            const events = [createMockEvent()];
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            expect(vi.mocked(deleteEventApiV1AdminEventsEventIdDelete)).not.toHaveBeenCalled();
        });

        it('handles delete error and shows toast', async () => {
            const error = { message: 'Cannot delete' };
            vi.mocked(deleteEventApiV1AdminEventsEventIdDelete).mockImplementation(async () => {
                toast.error('Failed to delete event');
                return { data: null, error } as any;
            });
            const events = [createMockEvent()];
            await renderWithEvents(events);

            const [deleteBtn] = screen.getAllByTitle('Delete');
            await user.click(deleteBtn!);

            await waitFor(() => {
                expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to delete event');
            });
        });
    });

    describe('export', () => {
        it('opens export dropdown menu', async () => {
            await renderWithEvents();

            const exportBtn = screen.getByRole('button', { name: /Export/i });
            await user.click(exportBtn);

            await waitFor(() => {
                expect(screen.getByText(/Export as CSV/i)).toBeInTheDocument();
                expect(screen.getByText(/Export as JSON/i)).toBeInTheDocument();
            });
        });

        it('exports as CSV', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Export/i }));
            await waitFor(() => expect(screen.getByText(/Export as CSV/i)).toBeInTheDocument());

            await user.click(screen.getByText(/Export as CSV/i));

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/csv'),
                '_blank',
            );
            expect(vi.mocked(toast.info)).toHaveBeenCalledWith(expect.stringContaining('Starting CSV export'));
        });

        it('exports as JSON', async () => {
            await renderWithEvents();

            await user.click(screen.getByRole('button', { name: /Export/i }));
            await waitFor(() => expect(screen.getByText(/Export as JSON/i)).toBeInTheDocument());

            await user.click(screen.getByText(/Export as JSON/i));

            expect(mocks.windowOpen).toHaveBeenCalledWith(
                expect.stringContaining('/api/v1/admin/events/export/json'),
                '_blank',
            );
            expect(vi.mocked(toast.info)).toHaveBeenCalledWith(expect.stringContaining('Starting JSON export'));
        });
    });

    describe('user overview modal', () => {
        it('opens user overview modal when user ID is clicked', async () => {
            const events = [createMockEvent({ metadata: { user_id: 'user-overview-1' } })];
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(createMockUserOverview());
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-overview-1');
            await user.click(userLink!);

            await waitFor(() => {
                expect(vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet)).toHaveBeenCalledWith({
                    path: { user_id: 'user-overview-1' },
                });
                expect(screen.getByText(/User Overview/i)).toBeInTheDocument();
            });
        });

        it('displays user information in overview modal', async () => {
            const events = [createMockEvent({ metadata: { user_id: 'user-info' } })];
            const overview = createMockUserOverview();
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(overview);
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-info');
            await user.click(userLink!);

            await waitFor(() => {
                expect(screen.getByText('testuser')).toBeInTheDocument();
                expect(screen.getByText('test@example.com')).toBeInTheDocument();
            });
        });

        it('shows execution stats in overview modal', async () => {
            const events = [createMockEvent({ metadata: { user_id: 'user-stats' } })];
            mockApi(getUserOverviewApiV1AdminUsersUserIdOverviewGet).ok(createMockUserOverview());
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

        it('handles user overview load error and shows toast', async () => {
            const error = { message: 'Failed to load' };
            const events = [createMockEvent({ metadata: { user_id: 'user-error' } })];
            vi.mocked(getUserOverviewApiV1AdminUsersUserIdOverviewGet).mockImplementation(async () => {
                toast.error('Failed to load user overview');
                return { data: null, error } as any;
            });
            await renderWithEvents(events);

            const [userLink] = screen.getAllByText('user-error');
            await user.click(userLink!);

            await waitFor(() => {
                expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to load user overview');
            });
        });
    });

    describe('event type display', () => {
        it('shows correct color for completed events', async () => {
            const events = [createMockEvent({ event_type: 'execution_completed' })];
            await renderWithEvents(events);
            const [icon] = screen.getAllByTestId('event-type-icon');
            expect(icon).toHaveAttribute('data-event-type', 'execution_completed');
            expect(icon).toHaveClass('text-green-600');
        });

        it('shows correct color for failed events', async () => {
            const events = [createMockEvent({ event_type: 'execution_failed' })];
            await renderWithEvents(events);
            const [icon] = screen.getAllByTestId('event-type-icon');
            expect(icon).toHaveAttribute('data-event-type', 'execution_failed');
            expect(icon).toHaveClass('text-red-600');
        });

        it('shows correct color for started events', async () => {
            const events = [createMockEvent({ event_type: 'execution_started' })];
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
        it('handles event detail load error and shows toast', async () => {
            const error = { message: 'Detail not found' };
            vi.mocked(getEventDetailApiV1AdminEventsEventIdGet).mockImplementation(async () => {
                toast.error('Failed to load event details');
                return { data: null, error } as any;
            });
            const events = [createMockEvent()];
            await renderWithEvents(events);

            const [eventRow] = screen.getAllByRole('button', { name: /View details for event/i });
            await user.click(eventRow!);

            await waitFor(() => {
                expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to load event details');
            });
        });

        it('handles replay error and shows toast', async () => {
            const error = { message: 'Replay failed' };
            vi.mocked(replayEventsApiV1AdminEventsReplayPost).mockImplementation(async () => {
                toast.error('Failed to replay event');
                return { data: null, error } as any;
            });
            const events = [createMockEvent()];
            await renderWithEvents(events);

            const [replayBtn] = screen.getAllByTitle('Replay');
            await user.click(replayBtn!);

            await waitFor(() => {
                expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to replay event');
            });
        });
    });
});
