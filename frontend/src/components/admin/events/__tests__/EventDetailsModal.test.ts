import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { createMockEventDetail, mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { getEventDetailApiV1AdminEventsEventIdGet, type EventDetailResponse } from '#lib/api/index.ts';

import EventDetailsModal from '#components/admin/events/EventDetailsModal.svelte';

function renderModal(detail: EventDetailResponse = createMockEventDetail()) {
    mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(detail);
    const onClose = vi.fn();
    const onReplay = vi.fn();
    const onViewRelated = vi.fn();
    const result = renderWithQueryClient(EventDetailsModal, { eventId: 'evt-1', onClose, onReplay, onViewRelated });
    return { ...result, onClose, onReplay, onViewRelated };
}

describe('EventDetailsModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('loads the event by its id', async () => {
        renderModal();
        await waitFor(() =>
            expect(vi.mocked(getEventDetailApiV1AdminEventsEventIdGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { event_id: 'evt-1' } }),
            ),
        );
    });

    it('shows the title before the event has loaded', () => {
        vi.mocked(getEventDetailApiV1AdminEventsEventIdGet).mockReturnValue(new Promise<never>(() => {}));
        renderWithQueryClient(EventDetailsModal, {
            eventId: 'evt-1',
            onClose: vi.fn(),
            onReplay: vi.fn(),
            onViewRelated: vi.fn(),
        });
        expect(screen.getByText('Event Details')).toBeInTheDocument();
        expect(screen.queryByText('Basic Information')).not.toBeInTheDocument();
    });

    it('shows the basic information once the event has loaded', async () => {
        renderModal();
        expect(await screen.findByText('Basic Information')).toBeInTheDocument();
    });

    it.each([
        { term: 'Event Id', value: 'evt-1' },
        { term: 'Event Type', value: 'execution_completed' },
        { term: 'Aggregate Id', value: 'exec-456' },
    ])('displays $term with value "$value"', async ({ term, value }) => {
        renderModal();
        const dt = await screen.findByText(term, { selector: 'dt' });
        expect(dt.nextElementSibling).toHaveTextContent(value);
    });

    it('shows full event JSON in pre block', async () => {
        renderModal();
        expect(await screen.findByRole('heading', { name: 'Event' })).toBeInTheDocument();
        const pre = document.querySelector('pre');
        expect(pre?.textContent).toContain('"event_id"');
        expect(pre?.textContent).toContain('"evt-1"');
    });

    it('shows related events section with clickable buttons', async () => {
        renderModal();
        expect(await screen.findByText('Related Events')).toBeInTheDocument();
        expect(screen.getByText('execution_started')).toBeInTheDocument();
        expect(screen.getByText('pod_created')).toBeInTheDocument();
    });

    it('calls onViewRelated with event_id when clicking a related event', async () => {
        const { onViewRelated } = renderModal();
        await user.click(await screen.findByText('execution_started'));
        expect(onViewRelated).toHaveBeenCalledWith('rel-1');
    });

    it('hides related events section when no related events', async () => {
        renderModal({ ...createMockEventDetail(), related_events: [] });
        await screen.findByText('Basic Information');
        expect(screen.queryByText('Related Events')).not.toBeInTheDocument();
    });

    it('calls onReplay with event_id when Replay Event button is clicked', async () => {
        const { onReplay } = renderModal();
        await screen.findByText('Basic Information');
        await user.click(screen.getByRole('button', { name: 'Replay Event' }));
        expect(onReplay).toHaveBeenCalledWith('evt-1');
    });

    it('calls onClose when Close button in footer is clicked', async () => {
        const { onClose } = renderModal();
        await user.click(screen.getByRole('button', { name: 'Close' }));
        expect(onClose).toHaveBeenCalledOnce();
    });
});
