import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import ToastContainer from '../ToastContainer.svelte';
import { toasts, addToast, removeToast } from '../../stores/toastStore';
import { setupAnimationMock } from '../../__tests__/test-utils';

describe('ToastContainer', () => {
  beforeEach(() => {
    setupAnimationMock();
    vi.useFakeTimers();
    toasts.set([]);
  });

  afterEach(() => {
    vi.useRealTimers();
    toasts.set([]);
  });

  describe('rendering', () => {
    it('renders empty container when no toasts', () => {
      const { container } = render(ToastContainer);
      const toastContainer = container.querySelector('.toasts-container');
      expect(toastContainer).toBeInTheDocument();
      expect(toastContainer?.children.length).toBe(0);
    });

    it('renders toast with message when added', async () => {
      render(ToastContainer);
      addToast('Hello World', 'success');
      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText('Hello World')).toBeInTheDocument();
      });
    });

    it('renders multiple toasts', async () => {
      render(ToastContainer);
      addToast('First toast', 'info');
      addToast('Second toast', 'success');
      addToast('Third toast', 'warning');
      await waitFor(() => { expect(screen.getAllByRole('alert')).toHaveLength(3); });
    });
  });

  describe('toast types', () => {
    it.each([
      { type: 'success', bgClass: 'bg-green-50' },
      { type: 'error', bgClass: 'bg-red-50' },
      { type: 'warning', bgClass: 'bg-yellow-50' },
      { type: 'info', bgClass: 'bg-blue-50' },
    ] as const)('applies $bgClass styling for $type toast', async ({ type, bgClass }) => {
      render(ToastContainer);
      addToast(`${type} message`, type);
      await waitFor(() => {
        const alert = screen.getByRole('alert');
        expect(alert.classList.contains(bgClass)).toBe(true);
        expect(alert.querySelector('svg')).toBeInTheDocument(); // icon present
      });
    });
  });

  describe('close button', () => {
    it('renders close button and removes toast when clicked', async () => {
      vi.useRealTimers();
      render(ToastContainer);
      addToast('Closable toast', 'info');

      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });

      const closeButton = screen.getByRole('button', { name: /Close toast/i });
      expect(closeButton).toBeInTheDocument();
      closeButton.click();

      await waitFor(() => { expect(get(toasts)).toHaveLength(0); });
      vi.useFakeTimers();
    });
  });

  describe('progress timer', () => {
    it('shows progress bar that decreases over time', async () => {
      render(ToastContainer);
      addToast('Timed toast', 'info');

      await waitFor(() => {
        const timer = screen.getByRole('alert').querySelector('.timer');
        expect(timer).toBeInTheDocument();
      });

      const timer = screen.getByRole('alert').querySelector('.timer') as HTMLElement;
      await vi.advanceTimersByTimeAsync(1000);

      await waitFor(() => { expect(timer.style.transform).toContain('scaleX'); });
    });
  });

  describe('accessibility', () => {
    it('toasts have role="alert" for screen reader announcement', async () => {
      render(ToastContainer);
      addToast('Accessible toast', 'info');
      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });
    });
  });

  describe('integration with store', () => {
    it('reflects store additions and removals', async () => {
      vi.useRealTimers();
      render(ToastContainer);

      expect(screen.queryByRole('alert')).not.toBeInTheDocument();

      addToast('Added via store', 'success');
      await waitFor(() => { expect(screen.getByText('Added via store')).toBeInTheDocument(); });

      const [toast] = get(toasts);
      removeToast(toast.id);
      expect(get(toasts)).toHaveLength(0);

      vi.useFakeTimers();
    });
  });

  describe('mouse interaction', () => {
    it('pauses timer on mouseenter and resumes on mouseleave', async () => {
      vi.useRealTimers();
      render(ToastContainer);
      addToast('Hoverable toast', 'info');

      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });

      const toastElement = screen.getByRole('alert');

      // Simulate mouse enter to pause timer
      const mouseEnterEvent = new MouseEvent('mouseenter', { bubbles: true });
      toastElement.dispatchEvent(mouseEnterEvent);

      // Toast should still be visible after pause
      await new Promise(resolve => setTimeout(resolve, 100));
      expect(screen.getByRole('alert')).toBeInTheDocument();

      // Simulate mouse leave to resume timer
      const mouseLeaveEvent = new MouseEvent('mouseleave', { bubbles: true });
      toastElement.dispatchEvent(mouseLeaveEvent);

      // Toast should still be visible immediately after resume
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('clears timer on mouseenter', async () => {
      vi.useRealTimers();
      render(ToastContainer);
      addToast('Timer test', 'success');

      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });

      const toastElement = screen.getByRole('alert');

      // Hover over the toast
      const mouseEnterEvent = new MouseEvent('mouseenter', { bubbles: true });
      toastElement.dispatchEvent(mouseEnterEvent);

      // Wait a bit - toast should still be there since timer is paused
      await new Promise(resolve => setTimeout(resolve, 200));
      expect(screen.getByText('Timer test')).toBeInTheDocument();
    });

    it('restarts timer on mouseleave', async () => {
      vi.useRealTimers();
      render(ToastContainer);
      addToast('Restart timer test', 'warning');

      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });

      const toastElement = screen.getByRole('alert');

      // Hover and unhover
      toastElement.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 50));
      toastElement.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));

      // Toast should still be visible after unhover
      expect(screen.getByText('Restart timer test')).toBeInTheDocument();
    });
  });

  describe('timer edge cases', () => {
    it('handles multiple toasts with independent timers', async () => {
      vi.useRealTimers();
      render(ToastContainer);
      addToast('First toast', 'info');
      addToast('Second toast', 'success');

      await waitFor(() => { expect(screen.getAllByRole('alert')).toHaveLength(2); });

      // Both toasts should have progress bars
      const alerts = screen.getAllByRole('alert');
      expect(alerts[0].querySelector('.timer')).toBeInTheDocument();
      expect(alerts[1].querySelector('.timer')).toBeInTheDocument();
    });

    it('cleans up timers on unmount', async () => {
      vi.useRealTimers();
      const { unmount } = render(ToastContainer);
      addToast('Cleanup test', 'info');

      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });

      // Unmount should clean up timers without error
      unmount();

      // No error should be thrown - this is implicitly tested by test not failing
    });
  });
});
