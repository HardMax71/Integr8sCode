import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import ErrorDisplay from '../ErrorDisplay.svelte';

describe('ErrorDisplay', () => {
  let originalLocation: Location;

  beforeEach(() => {
    // Mock window.location
    originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      value: {
        ...originalLocation,
        reload: vi.fn(),
        href: 'http://localhost:5001/test',
      },
      writable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
    });
  });

  describe('rendering', () => {
    it('renders with string error', () => {
      render(ErrorDisplay, { props: { error: 'Something went wrong' } });

      expect(screen.getByRole('heading')).toHaveTextContent('Application Error');
    });

    it('renders with Error object', () => {
      render(ErrorDisplay, { props: { error: new Error('Test error') } });

      expect(screen.getByRole('heading')).toHaveTextContent('Application Error');
    });

    it('displays custom title', () => {
      render(ErrorDisplay, {
        props: { error: 'Error', title: 'Custom Error Title' }
      });

      expect(screen.getByRole('heading')).toHaveTextContent('Custom Error Title');
    });

    it('uses default title when not provided', () => {
      render(ErrorDisplay, { props: { error: 'Error' } });

      expect(screen.getByRole('heading')).toHaveTextContent('Application Error');
    });
  });

  describe('user-friendly messages', () => {
    it('shows network error message for network errors', () => {
      render(ErrorDisplay, { props: { error: 'Network connection failed' } });

      expect(screen.getByText(/Unable to connect to the server/)).toBeInTheDocument();
    });

    it('shows network error message for fetch errors', () => {
      render(ErrorDisplay, { props: { error: new Error('Fetch failed') } });

      expect(screen.getByText(/Unable to connect to the server/)).toBeInTheDocument();
    });

    it('shows network error message for connection errors', () => {
      render(ErrorDisplay, { props: { error: 'Connection refused' } });

      expect(screen.getByText(/Unable to connect to the server/)).toBeInTheDocument();
    });

    it('shows generic message for non-network errors', () => {
      render(ErrorDisplay, { props: { error: 'Internal server error' } });

      expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
    });

    it('never exposes raw error details to user', () => {
      const sensitiveError = 'Database connection string: postgres://user:password@host';
      render(ErrorDisplay, { props: { error: sensitiveError } });

      expect(screen.queryByText(/postgres/)).not.toBeInTheDocument();
      expect(screen.queryByText(/password/)).not.toBeInTheDocument();
    });
  });

  describe('action buttons', () => {
    it('renders Reload Page button', () => {
      render(ErrorDisplay, { props: { error: 'Error' } });

      expect(screen.getByRole('button', { name: /Reload Page/i })).toBeInTheDocument();
    });

    it('renders Go to Home button', () => {
      render(ErrorDisplay, { props: { error: 'Error' } });

      expect(screen.getByRole('button', { name: /Go to Home/i })).toBeInTheDocument();
    });

    it('reloads page when Reload button clicked', async () => {
      const user = userEvent.setup();
      render(ErrorDisplay, { props: { error: 'Error' } });

      const reloadButton = screen.getByRole('button', { name: /Reload Page/i });
      await user.click(reloadButton);

      expect(window.location.reload).toHaveBeenCalled();
    });

    it('navigates to home when Go to Home clicked', async () => {
      const user = userEvent.setup();
      render(ErrorDisplay, { props: { error: 'Error' } });

      const homeButton = screen.getByRole('button', { name: /Go to Home/i });
      await user.click(homeButton);

      expect(window.location.href).toBe('/');
    });
  });

  describe('visual elements', () => {
    it('displays error icon', () => {
      render(ErrorDisplay, { props: { error: 'Error' } });

      const svg = document.querySelector('svg');
      expect(svg).toBeInTheDocument();
    });

    it('displays help text', () => {
      render(ErrorDisplay, { props: { error: 'Error' } });

      expect(screen.getByText(/If this problem persists/)).toBeInTheDocument();
    });
  });

  describe('styling', () => {
    it('has full-screen centered layout', () => {
      const { container } = render(ErrorDisplay, { props: { error: 'Error' } });

      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.classList.contains('min-h-screen')).toBe(true);
      expect(wrapper.classList.contains('flex')).toBe(true);
      expect(wrapper.classList.contains('items-center')).toBe(true);
      expect(wrapper.classList.contains('justify-center')).toBe(true);
    });
  });
});
