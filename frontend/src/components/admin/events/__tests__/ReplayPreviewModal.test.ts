import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import { EventType } from '#lib/api/index.ts';

import ReplayPreviewModal from '#components/admin/events/ReplayPreviewModal.svelte';
import type { ReplayPreview } from '#components/admin/events/ReplayPreviewModal.svelte';

function makePreview(overrides: Partial<ReplayPreview> = {}): ReplayPreview {
    return {
        eventId: 'evt-replay-1',
        total_events: 3,
        events_preview: [
            { event_id: 'e1', event_type: EventType.EXECUTION_REQUESTED, timestamp: '2024-01-15T10:00:00Z' },
            {
                event_id: 'e2',
                event_type: EventType.EXECUTION_COMPLETED,
                timestamp: '2024-01-15T10:01:00Z',
                aggregate_id: 'exec-1',
            },
        ],
        ...overrides,
    };
}

function renderModal(preview: ReplayPreview = makePreview()) {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    const result = render(ReplayPreviewModal, { props: { preview, onClose, onConfirm } });
    return { ...result, onClose, onConfirm };
}

describe('ReplayPreviewModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('shows modal title and description when open', () => {
        renderModal();
        expect(screen.getByText('Replay Preview')).toBeInTheDocument();
        expect(screen.getByText('Review the events that will be replayed')).toBeInTheDocument();
    });

    it.each([
        { total: 1, expected: '1 event will be replayed' },
        { total: 5, expected: '5 events will be replayed' },
    ])('shows "$expected" for total_events=$total (pluralization)', ({ total, expected }) => {
        renderModal(makePreview({ total_events: total }));
        expect(screen.getByText(expected)).toBeInTheDocument();
    });

    it('shows "Dry Run" badge', () => {
        renderModal();
        expect(screen.getByText('Dry Run')).toBeInTheDocument();
    });

    it('lists event previews with event_id, event_type, and aggregate_id', () => {
        renderModal();
        expect(screen.getByRole('heading', { name: 'Events Preview' })).toBeInTheDocument();
        expect(screen.getByText('e1')).toBeInTheDocument();
        expect(screen.getByText('execution_requested')).toBeInTheDocument();
        expect(screen.getByText('e2')).toBeInTheDocument();
        expect(screen.getByText('execution_completed')).toBeInTheDocument();
        expect(screen.getByText('Aggregate Id', { selector: 'dt' }).nextElementSibling).toHaveTextContent('exec-1');
    });

    it('hides events preview section when events_preview is empty', () => {
        renderModal(makePreview({ events_preview: [] }));
        expect(screen.queryByText('Events Preview')).not.toBeInTheDocument();
    });

    it('hides events preview section when events_preview is undefined', () => {
        renderModal(makePreview({ events_preview: undefined }));
        expect(screen.queryByText('Events Preview')).not.toBeInTheDocument();
    });

    it('shows warning banner about replay consequences', () => {
        renderModal();
        expect(screen.getByText('Warning')).toBeInTheDocument();
        expect(screen.getByText(/Replaying events will re-process them/)).toBeInTheDocument();
    });

    it('calls onConfirm with eventId and onClose when Proceed is clicked', async () => {
        const { onConfirm, onClose } = renderModal();
        await user.click(screen.getByRole('button', { name: 'Proceed with Replay' }));
        expect(onClose).toHaveBeenCalledOnce();
        expect(onConfirm).toHaveBeenCalledWith('evt-replay-1');
    });

    it('calls onClose when Cancel button is clicked', async () => {
        const { onClose, onConfirm } = renderModal();
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(onClose).toHaveBeenCalledOnce();
        expect(onConfirm).not.toHaveBeenCalled();
    });
});
