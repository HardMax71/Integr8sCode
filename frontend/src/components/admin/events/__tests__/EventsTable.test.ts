import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { createMockEvent, createMockEvents, user } from '$test/test-utils';

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('Eye', 'Play', 'Trash2'));
vi.mock('$components/EventTypeIcon.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<span>icon</span>'));

import EventsTable from '../EventsTable.svelte';

function renderTable(events = createMockEvents(3)) {
  const onViewDetails = vi.fn();
  const onPreviewReplay = vi.fn();
  const onReplay = vi.fn();
  const onDelete = vi.fn();
  const onViewUser = vi.fn();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const result = render(EventsTable, {
    props: { events: events as any, onViewDetails, onPreviewReplay, onReplay, onDelete, onViewUser },
  });
  return { ...result, onViewDetails, onPreviewReplay, onReplay, onDelete, onViewUser };
}

describe('EventsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows empty state when no events', () => {
    renderTable([]);
    expect(screen.getByText('No events found')).toBeInTheDocument();
  });

  it('renders table headers', () => {
    renderTable();
    expect(screen.getByText('Time')).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('User')).toBeInTheDocument();
    expect(screen.getByText('Service')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
  });

  it('renders one row per event in desktop table', () => {
    const events = createMockEvents(4);
    const { container } = renderTable(events);
    const rows = container.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(4);
  });

  it('renders mobile cards for each event', () => {
    const events = createMockEvents(2);
    const { container } = renderTable(events);
    const cards = container.querySelectorAll('.mobile-card');
    expect(cards).toHaveLength(2);
  });

  it('displays formatted timestamp in table rows', () => {
    const event = createMockEvent({ timestamp: '2024-06-15T14:30:00Z' });
    renderTable([event]);
    const date = new Date('2024-06-15T14:30:00Z');
    expect(screen.getByText(date.toLocaleDateString())).toBeInTheDocument();
    expect(screen.getByText(date.toLocaleTimeString())).toBeInTheDocument();
  });

  it('shows user_id as clickable link when present', () => {
    const event = createMockEvent({ metadata: { user_id: 'user-42' } });
    renderTable([event]);
    const userButtons = screen.getAllByTitle('View user overview');
    expect(userButtons.length).toBeGreaterThanOrEqual(1);
  });

  it('shows "-" when user_id is absent', () => {
    const event = createMockEvent({ metadata: { user_id: undefined } });
    renderTable([event]);
    const dashes = screen.getAllByText('-');
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it('shows service name in service column', () => {
    const event = createMockEvent({ metadata: { service_name: 'my-service' } });
    renderTable([event]);
    const serviceElements = screen.getAllByText('my-service');
    expect(serviceElements.length).toBeGreaterThanOrEqual(1);
  });

  describe('row click actions', () => {
    it('calls onViewDetails when clicking a table row', async () => {
      const events = [createMockEvent({ event_id: 'evt-click' })];
      const { onViewDetails } = renderTable(events);
      const rows = screen.getAllByRole('button', { name: 'View event details' });
      await user.click(rows[0]!);
      expect(onViewDetails).toHaveBeenCalledWith('evt-click');
    });

    it('calls onViewDetails on Enter keydown on table row', async () => {
      const events = [createMockEvent({ event_id: 'evt-key' })];
      const { onViewDetails } = renderTable(events);
      const rows = screen.getAllByRole('button', { name: 'View event details' });
      await fireEvent.keyDown(rows[0]!, { key: 'Enter' });
      expect(onViewDetails).toHaveBeenCalledWith('evt-key');
    });
  });

  describe('action buttons (stopPropagation)', () => {
    it.each([
      { title: 'Preview replay', callback: 'onPreviewReplay' as const },
      { title: 'Replay', callback: 'onReplay' as const },
      { title: 'Delete', callback: 'onDelete' as const },
    ])('$title button calls $callback with event_id without triggering row click', async ({ title, callback }) => {
      const events = [createMockEvent({ event_id: 'evt-action' })];
      const handlers = renderTable(events);
      const buttons = screen.getAllByTitle(title);
      await user.click(buttons[0]!);
      expect(handlers[callback]).toHaveBeenCalledWith('evt-action');
      expect(handlers.onViewDetails).not.toHaveBeenCalled();
    });
  });

  it('calls onViewUser with user_id when clicking user link (stopPropagation)', async () => {
    const event = createMockEvent({ metadata: { user_id: 'user-linked' } });
    const { onViewUser, onViewDetails } = renderTable([event]);
    const userButtons = screen.getAllByTitle('View user overview');
    await user.click(userButtons[0]!);
    expect(onViewUser).toHaveBeenCalledWith('user-linked');
    expect(onViewDetails).not.toHaveBeenCalled();
  });

  it('shows truncated event_id in tooltip', () => {
    const event = createMockEvent({ event_id: 'abcdefgh-1234-5678' });
    renderTable([event]);
    const truncated = screen.getAllByText('abcdefgh...');
    expect(truncated.length).toBeGreaterThanOrEqual(1);
  });
});
