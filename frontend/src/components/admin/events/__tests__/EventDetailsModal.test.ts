import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { getEventDetailApiV1AdminEventsEventIdGet, type EventDetailResponse } from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';
import {
    fakeEventDetailResponse,
    fakeEventSummary,
    fakeExecutionCompletedEvent,
} from '#lib/api/@faker-js/faker.gen.ts';

import EventDetailsModal from '#components/admin/events/EventDetailsModal.svelte';

function renderModal(
    detail: EventDetailResponse = {
        ...fakeEventDetailResponse(),
        event: {
            ...fakeExecutionCompletedEvent(),
            event_id: 'evt-1',
            aggregate_id: 'exec-456',
            timestamp: '2024-06-15T14:30:00Z',
        },
        related_events: [
            { ...fakeEventSummary(), event_id: 'rel-1', event_type: 'execution_started' },
            { ...fakeEventSummary(), event_id: 'rel-2', event_type: 'pod_created' },
        ],
    },
) {
    mockApi(getEventDetailApiV1AdminEventsEventIdGet).ok(detail);
    const onClose = vi.fn();
    const onReplay = vi.fn();
    const onViewRelated = vi.fn();
    const result = renderWithQueryClient(EventDetailsModal, { eventId: 'evt-1', onClose, onReplay, onViewRelated });
    return { ...result, onClose, onReplay, onViewRelated };
}

describe('EventDetailsModal', () => {
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

    it('lists each field of the event next to its value', async () => {
        renderModal();
        await screen.findByText('Basic Information');
        expect(screen.getAllByRole('term').map((term) => term.textContent)).toEqual(
            ['event_id', 'event_type', 'timestamp', 'aggregate_id'].map(fieldTitle),
        );
        expect(screen.getAllByRole('definition').map((definition) => definition.textContent?.trim())).toEqual([
            'evt-1',
            'execution_completed',
            'Jun 15, 2024, 02:30:00 PM',
            'exec-456',
        ]);
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
        renderModal({ ...fakeEventDetailResponse(), related_events: [] });
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
