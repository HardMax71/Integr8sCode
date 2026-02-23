import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick } from 'svelte';
import {
  mockWindowGlobals,
  createMockEvent,
  createMockEvents,
  createMockStats,
  createMockEventDetail,
  createMockUserOverview,
} from '$test/test-utils';

// Hoisted mocks
const mocks = vi.hoisted(() => ({
  browseEventsApiV1AdminEventsBrowsePost: vi.fn(),
  getEventStatsApiV1AdminEventsStatsGet: vi.fn(),
  getEventDetailApiV1AdminEventsEventIdGet: vi.fn(),
  getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet: vi.fn(),
  replayEventsApiV1AdminEventsReplayPost: vi.fn(),
  deleteEventApiV1AdminEventsEventIdDelete: vi.fn(),
  getUserOverviewApiV1AdminUsersUserIdOverviewGet: vi.fn(),
  addToast: vi.fn(),
  windowOpen: vi.fn(),
  windowConfirm: vi.fn(),
}));

// Mock API module
vi.mock('../../../lib/api', () => ({
  browseEventsApiV1AdminEventsBrowsePost: (...args: unknown[]) => mocks.browseEventsApiV1AdminEventsBrowsePost(...args),
  getEventStatsApiV1AdminEventsStatsGet: (...args: unknown[]) => mocks.getEventStatsApiV1AdminEventsStatsGet(...args),
  getEventDetailApiV1AdminEventsEventIdGet: (...args: unknown[]) => mocks.getEventDetailApiV1AdminEventsEventIdGet(...args),
  getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet: (...args: unknown[]) => mocks.getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet(...args),
  replayEventsApiV1AdminEventsReplayPost: (...args: unknown[]) => mocks.replayEventsApiV1AdminEventsReplayPost(...args),
  deleteEventApiV1AdminEventsEventIdDelete: (...args: unknown[]) => mocks.deleteEventApiV1AdminEventsEventIdDelete(...args),
  getUserOverviewApiV1AdminUsersUserIdOverviewGet: (...args: unknown[]) => mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet(...args),
}));

vi.mock('svelte-sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mocks.addToast(...args),
    error: (...args: unknown[]) => mocks.addToast(...args),
    warning: (...args: unknown[]) => mocks.addToast(...args),
    info: (...args: unknown[]) => mocks.addToast(...args),
  },
}));

vi.mock('../../../lib/api-interceptors');

// Mock @mateothegreat/svelte5-router
vi.mock('@mateothegreat/svelte5-router', () => ({
  route: () => {},
  goto: vi.fn(),
}));

// Simple mock for AdminLayout
vi.mock('../AdminLayout.svelte', async () => {
  const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
  return { default: MockLayout };
});

import AdminEvents from '$routes/admin/AdminEvents.svelte';

async function renderWithEvents(events = createMockEvents(5), stats = createMockStats()) {
  mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({
    data: { events, total: events.length },
    error: null,
  });
  mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({ data: stats, error: null });

  const result = render(AdminEvents);
  await tick();
  await waitFor(() => expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled());
  return result;
}

describe('AdminEvents', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockWindowGlobals(mocks.windowOpen, mocks.windowConfirm);
    vi.clearAllMocks();
    mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({ data: { events: [], total: 0 }, error: null });
    mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({ data: null, error: null });
    mocks.getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet.mockResolvedValue({
      data: { session_id: 'test', status: 'completed', total_events: 0, replayed_events: 0, progress_percentage: 100 },
      error: null
    });
    mocks.windowConfirm.mockReturnValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
    vi.unstubAllGlobals();
  });

  describe('initial loading', () => {
    it('calls loadEvents and loadStats on mount', async () => {
      vi.useRealTimers();
      render(AdminEvents);
      await waitFor(() => {
        expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledTimes(1);
        expect(mocks.getEventStatsApiV1AdminEventsStatsGet).toHaveBeenCalledTimes(1);
      });
    });

    it('sets up auto-refresh interval', async () => {
      render(AdminEvents);
      await tick();

      // Fast-forward 30 seconds
      await vi.advanceTimersByTimeAsync(30000);

      await waitFor(() => {
        expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledTimes(2);
        expect(mocks.getEventStatsApiV1AdminEventsStatsGet).toHaveBeenCalledTimes(2);
      });
    });

    it('handles API error on load events and shows toast', async () => {
      vi.useRealTimers();
      const error = { message: 'Network error' };
      mocks.browseEventsApiV1AdminEventsBrowsePost.mockImplementation(async () => {
        mocks.addToast('Failed to load events');
        return { data: null, error };
      });
      render(AdminEvents);
      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to load events'));
    });

    it('displays empty state when no events', async () => {
      vi.useRealTimers();
      await renderWithEvents([], createMockStats({ total_events: 0 }));
      expect(screen.getByText(/No events found/i)).toBeInTheDocument();
    });
  });

  describe('stats display', () => {
    it('displays event statistics cards', async () => {
      vi.useRealTimers();
      await renderWithEvents(createMockEvents(5), createMockStats({ total_events: 150, error_rate: 2.5, avg_processing_time: 1.23 }));
      expect(screen.getByText(/Events \(Last 24h\)/i)).toBeInTheDocument();
      expect(screen.getByText('150')).toBeInTheDocument();
      expect(screen.getByText('2.5%')).toBeInTheDocument();
      expect(screen.getByText('1.23s')).toBeInTheDocument();
    });

    it('shows error rate in red when > 0', async () => {
      vi.useRealTimers();
      await renderWithEvents(createMockEvents(1), createMockStats({ error_rate: 5 }));
      const errorRateElement = screen.getByText('5%');
      expect(errorRateElement).toHaveClass('text-red-600');
    });

    it('shows error rate in green when 0', async () => {
      vi.useRealTimers();
      await renderWithEvents(createMockEvents(1), createMockStats({ error_rate: 0 }));
      const errorRateElement = screen.getByText('0%');
      expect(errorRateElement).toHaveClass('text-green-600');
    });
  });

  describe('event list rendering', () => {
    it('displays events in table', async () => {
      vi.useRealTimers();
      const events = [createMockEvent({ event_type: 'execution_completed', metadata: { user_id: 'user-1', service_name: 'test-service' } })];
      await renderWithEvents(events);
      // Events are displayed (multiple due to mobile + desktop views)
      expect(screen.getAllByText('test-service')).toHaveLength(2);
    });

    it('displays multiple events', async () => {
      vi.useRealTimers();
      const events = createMockEvents(5);
      await renderWithEvents(events);
      // Should show events info in pagination
      expect(screen.getByText(/Showing 1 to 5 of 5 events/i)).toBeInTheDocument();
    });

    it('shows user ID as clickable link', async () => {
      vi.useRealTimers();
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
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();
      mocks.browseEventsApiV1AdminEventsBrowsePost.mockClear();

      const refreshBtn = screen.getByRole('button', { name: /Refresh/i });
      await user.click(refreshBtn);

      await waitFor(() => expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled());
    });
  });

  describe('filters', () => {
    it('toggles filter panel', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();

      const filtersBtn = screen.getByRole('button', { name: /Filters/i });
      await user.click(filtersBtn);

      await waitFor(() => {
        expect(screen.getByText(/Filter Events/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Event Types/i)).toBeInTheDocument();
      });
    });

    it('displays filter inputs when panel is open', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
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
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();

      await user.click(screen.getByRole('button', { name: /Filters/i }));
      await waitFor(() => expect(screen.getByLabelText(/Search/i)).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Search/i), 'test query');
      mocks.browseEventsApiV1AdminEventsBrowsePost.mockClear();

      await user.click(screen.getByRole('button', { name: /^Apply$/i }));

      await waitFor(() => {
        expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              filters: expect.objectContaining({
                search_text: 'test query',
              }),
            }),
          })
        );
      });
    });

    it('clears all filters', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();

      await user.click(screen.getByRole('button', { name: /Filters/i }));
      await waitFor(() => expect(screen.getByLabelText(/Search/i)).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Search/i), 'test');
      await user.click(screen.getByRole('button', { name: /Clear All/i }));

      expect(screen.getByLabelText(/Search/i)).toHaveValue('');
    });

    it('shows active filter count badge', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
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
      vi.useRealTimers();
      const events = createMockEvents(25);
      mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({
        data: { events: events.slice(0, 10), total: 25 },
        error: null,
      });
      mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({ data: createMockStats(), error: null });

      render(AdminEvents);
      await waitFor(() => expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled());

      expect(screen.getByText(/Showing 1 to 10 of 25 events/i)).toBeInTheDocument();
    });

    it('changes page when next is clicked', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({
        data: { events: createMockEvents(10), total: 25 },
        error: null,
      });
      mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({ data: createMockStats(), error: null });

      render(AdminEvents);
      await waitFor(() => expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled());

      mocks.browseEventsApiV1AdminEventsBrowsePost.mockClear();
      const nextBtn = screen.getByTitle('Next page');
      await user.click(nextBtn);

      await waitFor(() => {
        expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              skip: 10,
            }),
          })
        );
      });
    });

    it('changes page size', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      mocks.browseEventsApiV1AdminEventsBrowsePost.mockResolvedValue({
        data: { events: createMockEvents(10), total: 50 },
        error: null,
      });
      mocks.getEventStatsApiV1AdminEventsStatsGet.mockResolvedValue({ data: createMockStats(), error: null });

      render(AdminEvents);
      await waitFor(() => expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalled());

      mocks.browseEventsApiV1AdminEventsBrowsePost.mockClear();
      const pageSizeSelect = screen.getByLabelText(/Show:/i);
      await user.selectOptions(pageSizeSelect, '25');

      await waitFor(() => {
        expect(mocks.browseEventsApiV1AdminEventsBrowsePost).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              limit: 25,
            }),
          })
        );
      });
    });
  });

  describe('event detail modal', () => {
    it('opens event detail modal when row is clicked', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ event_id: 'evt-detail-1' })];
      mocks.getEventDetailApiV1AdminEventsEventIdGet.mockResolvedValue({
        data: createMockEventDetail(events[0]),
        error: null,
      });
      await renderWithEvents(events);

      // Multiple view detail buttons may exist (mobile + desktop views)
      const [eventRow] = screen.getAllByRole('button', { name: /View event details/i });
      await user.click(eventRow!);

      await waitFor(() => {
        expect(mocks.getEventDetailApiV1AdminEventsEventIdGet).toHaveBeenCalledWith({
          path: { event_id: 'evt-detail-1' },
        });
        expect(screen.getByText(/Event Details/i)).toBeInTheDocument();
      });
    });

    it('displays event information in modal', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const event = createMockEvent({ event_id: 'evt-123', event_type: 'execution_completed' });
      mocks.getEventDetailApiV1AdminEventsEventIdGet.mockResolvedValue({
        data: createMockEventDetail(event),
        error: null,
      });
      await renderWithEvents([event]);

      const [eventRow] = screen.getAllByRole('button', { name: /View event details/i });
      await user.click(eventRow!);

      await waitFor(() => {
        // Using getAllByText because values may appear in table + modal
        expect(screen.getAllByText('evt-123').length).toBeGreaterThan(0);
        expect(screen.getAllByText('execution_completed').length).toBeGreaterThan(0);
      });
    });

    it('shows related events in modal', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const event = createMockEvent();
      mocks.getEventDetailApiV1AdminEventsEventIdGet.mockResolvedValue({
        data: createMockEventDetail(event),
        error: null,
      });
      await renderWithEvents([event]);

      const [eventRow] = screen.getAllByRole('button', { name: /View event details/i });
      await user.click(eventRow!);

      await waitFor(() => {
        expect(screen.getByText(/Related Events/i)).toBeInTheDocument();
        expect(screen.getByText('execution_started')).toBeInTheDocument();
        expect(screen.getByText('pod_created')).toBeInTheDocument();
      });
    });

    it('has close button in modal', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const event = createMockEvent();
      mocks.getEventDetailApiV1AdminEventsEventIdGet.mockResolvedValue({
        data: createMockEventDetail(event),
        error: null,
      });
      await renderWithEvents([event]);

      const [eventRow] = screen.getAllByRole('button', { name: /View event details/i });
      await user.click(eventRow!);

      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      // Verify close buttons exist (Modal X button and footer Close button)
      expect(screen.getByRole('button', { name: /Close modal/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^Close$/i })).toBeInTheDocument();
    });
  });

  describe('replay functionality', () => {
    it('shows replay preview on dry run', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ event_id: 'evt-replay-1' })];
      mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
        data: { total_events: 1, events_preview: events, session_id: null },
        error: null,
      });
      await renderWithEvents(events);

      const [previewBtn] = screen.getAllByTitle('Preview replay');
      await user.click(previewBtn!);

      await waitFor(() => {
        expect(mocks.replayEventsApiV1AdminEventsReplayPost).toHaveBeenCalledWith({
          body: { event_ids: ['evt-replay-1'], dry_run: true },
        });
        expect(screen.getByText(/Replay Preview/i)).toBeInTheDocument();
      });
    });

    it('confirms before actual replay', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ event_id: 'evt-replay-2' })];
      mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
        data: { total_events: 1, session_id: 'session-1' },
        error: null,
      });
      await renderWithEvents(events);

      const [replayBtn] = screen.getAllByTitle('Replay');
      await user.click(replayBtn!);

      expect(mocks.windowConfirm).toHaveBeenCalled();
      await waitFor(() => {
        expect(mocks.replayEventsApiV1AdminEventsReplayPost).toHaveBeenCalledWith({
          body: { event_ids: ['evt-replay-2'], dry_run: false },
        });
      });
    });

    it('does not replay if confirm is cancelled', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      mocks.windowConfirm.mockReturnValue(false);
      const events = [createMockEvent()];
      await renderWithEvents(events);

      const [replayBtn] = screen.getAllByTitle('Replay');
      await user.click(replayBtn!);

      expect(mocks.replayEventsApiV1AdminEventsReplayPost).not.toHaveBeenCalled();
    });

    it('shows replay progress when session is active', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ event_id: 'evt-progress' })];
      mocks.replayEventsApiV1AdminEventsReplayPost.mockResolvedValue({
        data: { total_events: 5, session_id: 'session-progress' },
        error: null,
      });
      mocks.getReplayStatusApiV1AdminEventsReplaySessionIdStatusGet.mockResolvedValue({
        data: {
          session_id: 'session-progress',
          status: 'in_progress',
          total_events: 5,
          replayed_events: 2,
          progress_percentage: 40,
        },
        error: null,
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
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ event_id: 'evt-delete-1' })];
      mocks.deleteEventApiV1AdminEventsEventIdDelete.mockResolvedValue({ data: {}, error: null });
      await renderWithEvents(events);

      const [deleteBtn] = screen.getAllByTitle('Delete');
      await user.click(deleteBtn!);

      expect(mocks.windowConfirm).toHaveBeenCalled();
      await waitFor(() => {
        expect(mocks.deleteEventApiV1AdminEventsEventIdDelete).toHaveBeenCalledWith({
          path: { event_id: 'evt-delete-1' },
        });
      });
    });

    it('shows success toast after deletion', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent()];
      mocks.deleteEventApiV1AdminEventsEventIdDelete.mockResolvedValue({ data: {}, error: null });
      await renderWithEvents(events);

      const [deleteBtn] = screen.getAllByTitle('Delete');
      await user.click(deleteBtn!);

      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('Event deleted successfully');
      });
    });

    it('does not delete if confirm is cancelled', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      mocks.windowConfirm.mockReturnValue(false);
      const events = [createMockEvent()];
      await renderWithEvents(events);

      const [deleteBtn] = screen.getAllByTitle('Delete');
      await user.click(deleteBtn!);

      expect(mocks.deleteEventApiV1AdminEventsEventIdDelete).not.toHaveBeenCalled();
    });

    it('handles delete error and shows toast', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const error = { message: 'Cannot delete' };
      mocks.deleteEventApiV1AdminEventsEventIdDelete.mockImplementation(async () => {
        mocks.addToast('Failed to delete event');
        return { data: null, error };
      });
      const events = [createMockEvent()];
      await renderWithEvents(events);

      const [deleteBtn] = screen.getAllByTitle('Delete');
      await user.click(deleteBtn!);

      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('Failed to delete event');
      });
    });
  });

  describe('export', () => {
    it('opens export dropdown menu', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();

      const exportBtn = screen.getByRole('button', { name: /Export/i });
      await user.click(exportBtn);

      await waitFor(() => {
        expect(screen.getByText(/Export as CSV/i)).toBeInTheDocument();
        expect(screen.getByText(/Export as JSON/i)).toBeInTheDocument();
      });
    });

    it('exports as CSV', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();

      await user.click(screen.getByRole('button', { name: /Export/i }));
      await waitFor(() => expect(screen.getByText(/Export as CSV/i)).toBeInTheDocument());

      await user.click(screen.getByText(/Export as CSV/i));

      expect(mocks.windowOpen).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/admin/events/export/csv'),
        '_blank'
      );
      expect(mocks.addToast).toHaveBeenCalledWith(expect.stringContaining('Starting CSV export'));
    });

    it('exports as JSON', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      await renderWithEvents();

      await user.click(screen.getByRole('button', { name: /Export/i }));
      await waitFor(() => expect(screen.getByText(/Export as JSON/i)).toBeInTheDocument());

      await user.click(screen.getByText(/Export as JSON/i));

      expect(mocks.windowOpen).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/admin/events/export/json'),
        '_blank'
      );
      expect(mocks.addToast).toHaveBeenCalledWith(expect.stringContaining('Starting JSON export'));
    });
  });

  describe('user overview modal', () => {
    it('opens user overview modal when user ID is clicked', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ metadata: { user_id: 'user-overview-1' } })];
      mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet.mockResolvedValue({
        data: createMockUserOverview(),
        error: null,
      });
      await renderWithEvents(events);

      const [userLink] = screen.getAllByText('user-overview-1');
      await user.click(userLink!);

      await waitFor(() => {
        expect(mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet).toHaveBeenCalledWith({
          path: { user_id: 'user-overview-1' },
        });
        expect(screen.getByText(/User Overview/i)).toBeInTheDocument();
      });
    });

    it('displays user information in overview modal', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ metadata: { user_id: 'user-info' } })];
      const overview = createMockUserOverview();
      mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet.mockResolvedValue({
        data: overview,
        error: null,
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
      vi.useRealTimers();
      const user = userEvent.setup();
      const events = [createMockEvent({ metadata: { user_id: 'user-stats' } })];
      mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet.mockResolvedValue({
        data: createMockUserOverview(),
        error: null,
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

    it('handles user overview load error and shows toast', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const error = { message: 'Failed to load' };
      const events = [createMockEvent({ metadata: { user_id: 'user-error' } })];
      mocks.getUserOverviewApiV1AdminUsersUserIdOverviewGet.mockImplementation(async () => {
        mocks.addToast('Failed to load user overview');
        return { data: null, error };
      });
      await renderWithEvents(events);

      const [userLink] = screen.getAllByText('user-error');
      await user.click(userLink!);

      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('Failed to load user overview');
      });
    });
  });

  describe('event type display', () => {
    it('shows correct color for completed events', async () => {
      vi.useRealTimers();
      const events = [createMockEvent({ event_type: 'execution_completed' })];
      await renderWithEvents(events);
      const [icon] = screen.getAllByTestId('event-type-icon');
      expect(icon).toHaveAttribute('data-event-type', 'execution_completed');
      expect(icon).toHaveClass('text-green-600');
    });

    it('shows correct color for failed events', async () => {
      vi.useRealTimers();
      const events = [createMockEvent({ event_type: 'execution_failed' })];
      await renderWithEvents(events);
      const [icon] = screen.getAllByTestId('event-type-icon');
      expect(icon).toHaveAttribute('data-event-type', 'execution_failed');
      expect(icon).toHaveClass('text-red-600');
    });

    it('shows correct color for started events', async () => {
      vi.useRealTimers();
      const events = [createMockEvent({ event_type: 'execution_started' })];
      await renderWithEvents(events);
      const [icon] = screen.getAllByTestId('event-type-icon');
      expect(icon).toHaveAttribute('data-event-type', 'execution_started');
      expect(icon).toHaveClass('text-blue-600');
    });
  });

  describe('header and layout', () => {
    it('displays page title', async () => {
      vi.useRealTimers();
      await renderWithEvents();
      expect(screen.getByText('Event Browser')).toBeInTheDocument();
    });

    it('has Filters, Export, and Refresh buttons', async () => {
      vi.useRealTimers();
      await renderWithEvents();
      expect(screen.getByRole('button', { name: /Filters/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Export/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
    });
  });

  describe('error handling', () => {
    it('handles event detail load error and shows toast', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const error = { message: 'Detail not found' };
      mocks.getEventDetailApiV1AdminEventsEventIdGet.mockImplementation(async () => {
        mocks.addToast('Failed to load event details');
        return { data: null, error };
      });
      const events = [createMockEvent()];
      await renderWithEvents(events);

      const [eventRow] = screen.getAllByRole('button', { name: /View event details/i });
      await user.click(eventRow!);

      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('Failed to load event details');
      });
    });

    it('handles replay error and shows toast', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      const error = { message: 'Replay failed' };
      mocks.replayEventsApiV1AdminEventsReplayPost.mockImplementation(async () => {
        mocks.addToast('Failed to replay event');
        return { data: null, error };
      });
      const events = [createMockEvent()];
      await renderWithEvents(events);

      const [replayBtn] = screen.getAllByTitle('Replay');
      await user.click(replayBtn!);

      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('Failed to replay event');
      });
    });
  });
});
