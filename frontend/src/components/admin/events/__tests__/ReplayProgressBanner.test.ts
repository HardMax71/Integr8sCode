import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import type { EventReplayStatusResponse } from '$lib/api';

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('X'));

import ReplayProgressBanner from '../ReplayProgressBanner.svelte';

function makeSession(overrides: Partial<EventReplayStatusResponse> = {}): EventReplayStatusResponse {
  return {
    session_id: 'session-1',
    status: 'in_progress',
    total_events: 10,
    replayed_events: 5,
    progress_percentage: 50,
    ...overrides,
  };
}

function renderBanner(session: EventReplayStatusResponse | null = makeSession()) {
  const onClose = vi.fn();
  const result = render(ReplayProgressBanner, { props: { session, onClose } });
  return { ...result, onClose };
}

describe('ReplayProgressBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when session is null', () => {
    const { container } = renderBanner(null);
    expect(container.textContent?.trim()).toBe('');
  });

  it('shows title and status', () => {
    renderBanner(makeSession({ status: 'in_progress' }));
    expect(screen.getByText('Replay in Progress')).toBeInTheDocument();
    expect(screen.getByText('in_progress')).toBeInTheDocument();
  });

  it('shows progress text and percentage', () => {
    renderBanner(makeSession({ replayed_events: 7, total_events: 20, progress_percentage: 35 }));
    expect(screen.getByText('Progress: 7 / 20 events')).toBeInTheDocument();
    expect(screen.getByText('35%')).toBeInTheDocument();
  });

  it('renders progress bar with correct width', () => {
    const { container } = renderBanner(makeSession({ progress_percentage: 75 }));
    const bar = container.querySelector('.bg-blue-600');
    expect(bar).not.toBeNull();
    expect(bar?.getAttribute('style')).toContain('width: 75%');
  });

  it('clamps progress bar width to 100%', () => {
    const { container } = renderBanner(makeSession({ progress_percentage: 150 }));
    const bar = container.querySelector('.bg-blue-600');
    expect(bar?.getAttribute('style')).toContain('width: 100%');
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();
    const { onClose } = renderBanner();
    await user.click(screen.getByTitle('Close'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  describe('errors', () => {
    it('hides error section when no errors', () => {
      renderBanner(makeSession({ errors: [] }));
      expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    });

    it('shows errors with event_id and error message', () => {
      renderBanner(makeSession({
        errors: [
          { event_id: 'err-evt-1', error: 'Timeout exceeded' },
          { error: 'Connection refused' },
        ],
      }));
      expect(screen.getByText('err-evt-1')).toBeInTheDocument();
      expect(screen.getByText('Timeout exceeded')).toBeInTheDocument();
      expect(screen.getByText('Connection refused')).toBeInTheDocument();
    });
  });

  describe('execution results', () => {
    it('hides execution results section when not present', () => {
      renderBanner(makeSession());
      expect(screen.queryByText('Execution Results:')).not.toBeInTheDocument();
    });

    it('shows execution results with status badges and execution_id', () => {
      renderBanner(makeSession({
        execution_results: [
          {
            execution_id: 'exec-r1',
            status: 'completed',
            stdout: 'hello',
            stderr: null,
            lang: 'python',
            lang_version: '3.11',
            resource_usage: { execution_time_wall_seconds: 1.23, cpu_time_jiffies: 10, peak_memory_kb: 1024 },
            exit_code: 0,
            error_type: null,
          },
        ],
      }));
      expect(screen.getByText('Execution Results:')).toBeInTheDocument();
      expect(screen.getByText('exec-r1')).toBeInTheDocument();
      expect(screen.getByText('completed')).toBeInTheDocument();
      expect(screen.getByText('1.23s')).toBeInTheDocument();
      expect(screen.getByText('hello')).toBeInTheDocument();
    });

    it.each([
      { status: 'completed', expectedClass: 'bg-green-100' },
      { status: 'failed', expectedClass: 'bg-red-100' },
      { status: 'running', expectedClass: 'bg-yellow-100' },
    ])('status "$status" shows badge with $expectedClass', ({ status, expectedClass }) => {
      const { container } = renderBanner(makeSession({
        execution_results: [{
          execution_id: 'exec-x',
          status,
          stdout: null,
          stderr: null,
          lang: 'python',
          lang_version: '3.11',
          resource_usage: null,
          exit_code: 0,
          error_type: null,
        }],
      }));
      expect(container.querySelector(`.${expectedClass}`)).not.toBeNull();
    });

    it('shows stderr in red when present', () => {
      renderBanner(makeSession({
        execution_results: [{
          execution_id: 'exec-err',
          status: 'failed',
          stdout: null,
          stderr: 'NameError',
          lang: 'python',
          lang_version: '3.11',
          resource_usage: null,
          exit_code: 1,
          error_type: null,
        }],
      }));
      expect(screen.getByText('NameError')).toBeInTheDocument();
    });
  });
});
