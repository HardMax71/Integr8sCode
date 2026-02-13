import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock } from '$test/test-utils';
import { createMockEventDetail } from '$routes/admin/__tests__/test-utils';

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('X'));
vi.mock('$components/EventTypeIcon.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<span>icon</span>'));

import EventDetailsModal from '../EventDetailsModal.svelte';

function renderModal(overrides: Partial<{
  event: ReturnType<typeof createMockEventDetail> | null;
  open: boolean;
}> = {}) {
  const onClose = vi.fn();
  const onReplay = vi.fn();
  const onViewRelated = vi.fn();
  const event = 'event' in overrides ? overrides.event : createMockEventDetail();
  const open = overrides.open ?? true;
  const result = render(EventDetailsModal, { props: { event, open, onClose, onReplay, onViewRelated } });
  return { ...result, onClose, onReplay, onViewRelated };
}

describe('EventDetailsModal', () => {
  beforeEach(() => {
    setupAnimationMock();
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    renderModal({ open: false });
    expect(screen.queryByText('Event Details')).not.toBeInTheDocument();
  });

  it('renders nothing when event is null', () => {
    renderModal({ event: null });
    expect(screen.queryByText('Basic Information')).not.toBeInTheDocument();
  });

  it('shows modal title and basic information heading when open with event', () => {
    renderModal();
    expect(screen.getByText('Event Details')).toBeInTheDocument();
    expect(screen.getByText('Basic Information')).toBeInTheDocument();
  });

  it.each([
    { label: 'Event ID', value: 'evt-1' },
    { label: 'Event Type', value: 'execution_completed' },
    { label: 'Aggregate ID', value: 'exec-456' },
  ])('displays $label with value "$value"', ({ label, value }) => {
    renderModal();
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(value)).toBeInTheDocument();
  });

  it('shows full event JSON in pre block', () => {
    const detail = createMockEventDetail();
    renderModal({ event: detail });
    expect(screen.getByText('Full Event Data')).toBeInTheDocument();
    const pre = document.querySelector('pre');
    expect(pre?.textContent).toContain('"event_id"');
    expect(pre?.textContent).toContain('"evt-1"');
  });

  it('shows related events section with clickable buttons', () => {
    renderModal();
    expect(screen.getByText('Related Events')).toBeInTheDocument();
    expect(screen.getByText('execution_started')).toBeInTheDocument();
    expect(screen.getByText('pod_created')).toBeInTheDocument();
  });

  it('calls onViewRelated with event_id when clicking a related event', async () => {
    const user = userEvent.setup();
    const { onViewRelated } = renderModal();
    await user.click(screen.getByText('execution_started'));
    expect(onViewRelated).toHaveBeenCalledWith('rel-1');
  });

  it('hides related events section when no related events', () => {
    const detail = createMockEventDetail();
    detail.related_events = [];
    renderModal({ event: detail });
    expect(screen.queryByText('Related Events')).not.toBeInTheDocument();
  });

  it('calls onReplay with event_id when Replay Event button is clicked', async () => {
    const user = userEvent.setup();
    const { onReplay } = renderModal();
    await user.click(screen.getByRole('button', { name: 'Replay Event' }));
    expect(onReplay).toHaveBeenCalledWith('evt-1');
  });

  it('calls onClose when Close button in footer is clicked', async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

});
