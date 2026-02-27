import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import EventTypeIcon from '$components/EventTypeIcon.svelte';

describe('EventTypeIcon', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('known event types', () => {
    it.each([
      'execution.requested',
      'execution_requested',
      'execution.started',
      'execution_started',
      'execution.completed',
      'execution_completed',
      'execution.failed',
      'execution_failed',
      'execution.timeout',
      'execution_timeout',
      'pod.created',
      'pod_created',
      'pod.running',
      'pod_running',
      'pod.succeeded',
      'pod_succeeded',
      'pod.failed',
      'pod_failed',
      'pod.terminated',
      'pod_terminated',
    ])('renders SVG for "%s"', (eventType) => {
      const { container } = render(EventTypeIcon, { props: { eventType } });
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg?.classList.contains('lucide-help-circle')).toBe(false);
    });
  });

  describe('unknown event type', () => {
    it('renders fallback icon for unknown type', () => {
      const { container } = render(EventTypeIcon, { props: { eventType: 'unknown.event' } });
      expect(container.querySelector('svg')).toBeInTheDocument();
    });

    it('renders a different icon than known types', () => {
      const { container: unknownContainer } = render(EventTypeIcon, {
        props: { eventType: 'unknown.event' },
      });
      const { container: knownContainer } = render(EventTypeIcon, {
        props: { eventType: 'execution.started' },
      });
      expect(unknownContainer.querySelector('svg')?.innerHTML).not.toBe(
        knownContainer.querySelector('svg')?.innerHTML
      );
    });
  });

  describe('size prop', () => {
    it.each([
      { size: undefined, expected: '20', desc: 'defaults to 20' },
      { size: 32, expected: '32', desc: 'passes custom size' },
    ])('$desc', ({ size, expected }) => {
      const { container } = render(EventTypeIcon, {
        props: { eventType: 'execution.started', ...(size ? { size } : {}) },
      });
      const svg = container.querySelector('svg');
      expect(svg).toHaveAttribute('width', expected);
      expect(svg).toHaveAttribute('height', expected);
    });
  });
});
