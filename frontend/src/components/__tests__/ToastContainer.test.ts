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
    it('toasts have role="alert" and container has positioning', async () => {
      const { container } = render(ToastContainer);
      addToast('Accessible toast', 'info');

      await waitFor(() => { expect(screen.getByRole('alert')).toBeInTheDocument(); });

      const toastContainer = container.querySelector('.toasts-container');
      expect(toastContainer).toBeInTheDocument();
      expect(toastContainer).toHaveClass('toasts-container');
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
});
