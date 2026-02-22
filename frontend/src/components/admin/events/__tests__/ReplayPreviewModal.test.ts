import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock } from '$test/test-utils';

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('AlertTriangle', 'X'));

import ReplayPreviewModal from '../ReplayPreviewModal.svelte';

interface ReplayPreview {
  eventId: string;
  total_events: number;
  events_preview?: Array<{
    event_id: string;
    event_type: string;
    timestamp: string;
    aggregate_id?: string;
  }>;
}

function makePreview(overrides: Partial<ReplayPreview> = {}): ReplayPreview {
  return {
    eventId: 'evt-replay-1',
    total_events: 3,
    events_preview: [
      { event_id: 'e1', event_type: 'execution_requested', timestamp: '2024-01-15T10:00:00Z' },
      { event_id: 'e2', event_type: 'execution_completed', timestamp: '2024-01-15T10:01:00Z', aggregate_id: 'exec-1' },
    ],
    ...overrides,
  };
}

function renderModal(overrides: Partial<{ preview: ReplayPreview | null; open: boolean }> = {}) {
  const onClose = vi.fn();
  const onConfirm = vi.fn();
  const preview = ('preview' in overrides ? overrides.preview : makePreview()) ?? null;
  const open = overrides.open ?? true;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const result = render(ReplayPreviewModal, { props: { preview: preview as any, open, onClose, onConfirm } });
  return { ...result, onClose, onConfirm };
}

describe('ReplayPreviewModal', () => {
  beforeEach(() => {
    setupAnimationMock();
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    renderModal({ open: false });
    expect(screen.queryByText('Replay Preview')).not.toBeInTheDocument();
  });

  it('renders nothing visible when preview is null', () => {
    renderModal({ preview: null });
    expect(screen.queryByText(/event.*will be replayed/i)).not.toBeInTheDocument();
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
    renderModal({ preview: makePreview({ total_events: total }) });
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('shows "Dry Run" badge', () => {
    renderModal();
    expect(screen.getByText('Dry Run')).toBeInTheDocument();
  });

  it('lists event previews with event_id, event_type, and aggregate_id', () => {
    renderModal();
    expect(screen.getByText('Events to Replay:')).toBeInTheDocument();
    expect(screen.getByText('e1')).toBeInTheDocument();
    expect(screen.getByText('execution_requested')).toBeInTheDocument();
    expect(screen.getByText('e2')).toBeInTheDocument();
    expect(screen.getByText('execution_completed')).toBeInTheDocument();
    expect(screen.getByText('Aggregate: exec-1')).toBeInTheDocument();
  });

  it('hides events preview section when events_preview is empty', () => {
    renderModal({ preview: makePreview({ events_preview: [] }) });
    expect(screen.queryByText('Events to Replay:')).not.toBeInTheDocument();
  });

  it('hides events preview section when events_preview is undefined', () => {
    renderModal({ preview: makePreview({ events_preview: undefined }) });
    expect(screen.queryByText('Events to Replay:')).not.toBeInTheDocument();
  });

  it('shows warning banner about replay consequences', () => {
    renderModal();
    expect(screen.getByText('Warning')).toBeInTheDocument();
    expect(screen.getByText(/Replaying events will re-process them/)).toBeInTheDocument();
  });

  it('calls onConfirm with eventId and onClose when Proceed is clicked', async () => {
    const user = userEvent.setup();
    const { onConfirm, onClose } = renderModal();
    await user.click(screen.getByRole('button', { name: 'Proceed with Replay' }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onConfirm).toHaveBeenCalledWith('evt-replay-1');
  });

  it('calls onClose when Cancel button is clicked', async () => {
    const user = userEvent.setup();
    const { onClose, onConfirm } = renderModal();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
