import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, within } from '@testing-library/svelte';
import { createMockEvent, createMockEvents, renderWithQueryClient, user } from '#test/test-utils.ts';

import EventsTable from '#components/admin/events/EventsTable.svelte';

function renderTable(events = createMockEvents(3), rowCount = events.length) {
    const onViewDetails = vi.fn();
    const onPreviewReplay = vi.fn();
    const onReplay = vi.fn();
    const onDelete = vi.fn();
    const onViewUser = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const result = renderWithQueryClient(EventsTable, {
        events: events as any,
        rowCount,
        pagination: { pageIndex: 0, pageSize: 10 },
        loading: false,
        onViewDetails,
        onPreviewReplay,
        onReplay,
        onDelete,
        onViewUser,
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

    it.each(['Timestamp', 'Event Type', 'User Id', 'Service Name', 'Actions'])('renders the %s header', (header) => {
        renderTable();
        expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    });

    it('renders one row per event in desktop table', () => {
        const events = createMockEvents(4);
        const { container } = renderTable(events);
        const rows = container.querySelectorAll('tbody tr');
        expect(rows).toHaveLength(4);
    });

    it('renders a card for each event for narrow screens', () => {
        renderTable(createMockEvents(2));
        expect(within(screen.getByRole('list', { name: 'Events' })).getAllByRole('listitem')).toHaveLength(2);
    });

    it('shows the page range and the total', () => {
        renderTable(createMockEvents(10), 42);
        expect(screen.getByText('Showing 1 - 10 of 42 events')).toBeInTheDocument();
    });

    it('displays formatted timestamp in table rows', () => {
        const event = createMockEvent({ timestamp: '2024-06-15T14:30:00Z' });
        renderTable([event]);
        const date = new Date('2024-06-15T14:30:00Z');
        const dateOpts: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
        const timeOpts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit' };
        const table = within(screen.getByRole('table', { name: 'Events' }));
        expect(table.getByText(date.toLocaleDateString(undefined, dateOpts))).toBeInTheDocument();
        expect(table.getByText(date.toLocaleTimeString(undefined, timeOpts))).toBeInTheDocument();
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

    describe('details button', () => {
        it('calls onViewDetails when the time is clicked', async () => {
            const { onViewDetails } = renderTable([createMockEvent({ event_id: 'evt-click' })]);
            await user.click(screen.getAllByRole('button', { name: /^View details for event/ })[0]!);
            expect(onViewDetails).toHaveBeenCalledWith('evt-click');
        });

        it('opens the details from the keyboard', async () => {
            const { onViewDetails } = renderTable([createMockEvent({ event_id: 'evt-key' })]);
            screen.getAllByRole('button', { name: /^View details for event/ })[0]!.focus();
            await user.keyboard('{Enter}');
            expect(onViewDetails).toHaveBeenCalledWith('evt-key');
        });
    });

    describe('action buttons', () => {
        it.each([
            { title: 'Preview replay', callback: 'onPreviewReplay' as const },
            { title: 'Replay', callback: 'onReplay' as const },
            { title: 'Delete', callback: 'onDelete' as const },
        ])('$title button calls $callback with event_id and nothing else', async ({ title, callback }) => {
            const events = [createMockEvent({ event_id: 'evt-action' })];
            const handlers = renderTable(events);
            const buttons = screen.getAllByTitle(title);
            await user.click(buttons[0]!);
            expect(handlers[callback]).toHaveBeenCalledWith('evt-action');
            expect(handlers.onViewDetails).not.toHaveBeenCalled();
        });
    });

    it('calls onViewUser with user_id when clicking user link', async () => {
        const event = createMockEvent({ metadata: { user_id: 'user-linked' } });
        const { onViewUser, onViewDetails } = renderTable([event]);
        const userButtons = screen.getAllByTitle('View user overview');
        await user.click(userButtons[0]!);
        expect(onViewUser).toHaveBeenCalledWith('user-linked');
        expect(onViewDetails).not.toHaveBeenCalled();
    });

    it('shows the event type and the short id in a tooltip on keyboard focus', async () => {
        renderTable([createMockEvent({ event_id: 'abcdefgh-1234-5678', event_type: 'execution_requested' })]);
        expect(screen.queryByText('abcdefgh...')).not.toBeInTheDocument();

        const trigger = screen.getAllByRole('button', { name: 'execution_requested' })[0]!;
        while (document.activeElement !== trigger) await user.tab();

        const tooltip = (await screen.findByText('abcdefgh...')).closest('[data-tooltip-content]');
        expect(tooltip).toHaveTextContent('execution_requested');
    });
});
