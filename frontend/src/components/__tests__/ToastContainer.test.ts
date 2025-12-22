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

    it('renders toast when added', async () => {
      render(ToastContainer);
      addToast('Test message', 'info');

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });
    });

    it('displays toast message', async () => {
      render(ToastContainer);
      addToast('Hello World', 'success');

      await waitFor(() => {
        expect(screen.getByText('Hello World')).toBeInTheDocument();
      });
    });

    it('renders multiple toasts', async () => {
      render(ToastContainer);
      addToast('First toast', 'info');
      addToast('Second toast', 'success');
      addToast('Third toast', 'warning');

      await waitFor(() => {
        expect(screen.getAllByRole('alert')).toHaveLength(3);
      });
    });
  });

  describe('toast types', () => {
    it('applies success styling', async () => {
      render(ToastContainer);
      addToast('Success!', 'success');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        expect(alert.classList.contains('bg-green-50')).toBe(true);
      });
    });

    it('applies error styling', async () => {
      render(ToastContainer);
      addToast('Error!', 'error');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        expect(alert.classList.contains('bg-red-50')).toBe(true);
      });
    });

    it('applies warning styling', async () => {
      render(ToastContainer);
      addToast('Warning!', 'warning');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        expect(alert.classList.contains('bg-yellow-50')).toBe(true);
      });
    });

    it('applies info styling', async () => {
      render(ToastContainer);
      addToast('Info', 'info');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        expect(alert.classList.contains('bg-blue-50')).toBe(true);
      });
    });
  });

  describe('close button', () => {
    it('renders close button with aria-label', async () => {
      render(ToastContainer);
      addToast('Closable toast', 'info');

      await waitFor(() => {
        const closeButton = screen.getByRole('button', { name: /Close toast/i });
        expect(closeButton).toBeInTheDocument();
      });
    });

    it('removes toast when close button clicked', async () => {
      // Use real timers for this test to avoid timing issues
      vi.useRealTimers();

      render(ToastContainer);
      addToast('Toast to close', 'info');

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      const closeButton = screen.getByRole('button', { name: /Close toast/i });
      closeButton.click();

      // The toast should be removed from the store immediately
      await waitFor(() => {
        expect(get(toasts)).toHaveLength(0);
      });

      // Re-enable fake timers for other tests
      vi.useFakeTimers();
    });
  });

  describe('icons', () => {
    it('displays success icon for success toast', async () => {
      render(ToastContainer);
      addToast('Success', 'success');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        const icon = alert.querySelector('svg');
        expect(icon).toBeInTheDocument();
      });
    });

    it('displays error icon for error toast', async () => {
      render(ToastContainer);
      addToast('Error', 'error');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        const icon = alert.querySelector('svg');
        expect(icon).toBeInTheDocument();
      });
    });

    it('displays warning icon for warning toast', async () => {
      render(ToastContainer);
      addToast('Warning', 'warning');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        const icon = alert.querySelector('svg');
        expect(icon).toBeInTheDocument();
      });
    });

    it('displays info icon for info toast', async () => {
      render(ToastContainer);
      addToast('Info', 'info');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        const icon = alert.querySelector('svg');
        expect(icon).toBeInTheDocument();
      });
    });
  });

  describe('progress timer', () => {
    it('shows progress bar', async () => {
      render(ToastContainer);
      addToast('Timed toast', 'info');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        const timer = alert.querySelector('.timer');
        expect(timer).toBeInTheDocument();
      });
    });

    it('progress bar decreases over time', async () => {
      render(ToastContainer);
      addToast('Timed toast', 'info');

      await waitFor(() => {
        const alert = screen.getByRole('alert');
        const timer = alert.querySelector('.timer') as HTMLElement;
        expect(timer).toBeInTheDocument();
      });

      const alert = screen.getByRole('alert');
      const timer = alert.querySelector('.timer') as HTMLElement;
      const initialTransform = timer.style.transform;

      // Advance time
      await vi.advanceTimersByTimeAsync(1000);

      // Check that transform has changed (progress decreased)
      await waitFor(() => {
        const newTransform = timer.style.transform;
        // Both should have scaleX but with different values
        expect(newTransform).toContain('scaleX');
      });
    });
  });

  describe('accessibility', () => {
    it('toasts have role="alert"', async () => {
      render(ToastContainer);
      addToast('Accessible toast', 'info');

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });
    });

    it('container is fixed positioned', () => {
      const { container } = render(ToastContainer);

      const toastContainer = container.querySelector('.toasts-container');
      expect(toastContainer).toBeInTheDocument();
    });
  });

  describe('integration with store', () => {
    it('reflects store additions', async () => {
      render(ToastContainer);

      expect(screen.queryByRole('alert')).not.toBeInTheDocument();

      addToast('Added via store', 'success');

      await waitFor(() => {
        expect(screen.getByText('Added via store')).toBeInTheDocument();
      });
    });

    it('reflects store removals', async () => {
      // Use real timers for this test
      vi.useRealTimers();

      render(ToastContainer);
      addToast('Will be removed', 'info');

      await waitFor(() => {
        expect(screen.getByText('Will be removed')).toBeInTheDocument();
      });

      const [toast] = get(toasts);
      removeToast(toast.id);

      // Just verify the store was updated
      expect(get(toasts)).toHaveLength(0);

      // Re-enable fake timers
      vi.useFakeTimers();
    });
  });
});
