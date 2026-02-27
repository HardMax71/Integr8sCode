import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import StatusBadge from '../StatusBadge.svelte';

describe('StatusBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders status text', () => {
    render(StatusBadge, { props: { status: 'Running' } });
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  describe('color', () => {
    it('defaults to badge-neutral', () => {
      render(StatusBadge, { props: { status: 'Test' } });
      const badge = screen.getByText('Test');
      expect(badge.classList.contains('badge-neutral')).toBe(true);
    });

    it('applies custom color class', () => {
      render(StatusBadge, { props: { status: 'Test', color: 'badge-success' } });
      const badge = screen.getByText('Test');
      expect(badge.classList.contains('badge-success')).toBe(true);
    });
  });

  describe('size', () => {
    it.each([
      { size: 'sm' as const, expectedClass: 'text-xs' },
      { size: 'md' as const, expectedClass: 'text-sm' },
      { size: 'lg' as const, expectedClass: 'text-base' },
    ])('applies $expectedClass for size=$size', ({ size, expectedClass }) => {
      render(StatusBadge, { props: { status: 'Test', size } });
      const badge = screen.getByText('Test');
      expect(badge.classList.contains(expectedClass)).toBe(true);
    });

    it('defaults to md (text-sm)', () => {
      render(StatusBadge, { props: { status: 'Test' } });
      const badge = screen.getByText('Test');
      expect(badge.classList.contains('text-sm')).toBe(true);
    });
  });

  describe('suffix', () => {
    it('shows suffix with ml-1 span when provided', () => {
      render(StatusBadge, { props: { status: 'Running', suffix: '(3s)' } });
      expect(screen.getByText('(3s)')).toBeInTheDocument();
      const suffixEl = screen.getByText('(3s)');
      expect(suffixEl.classList.contains('ml-1')).toBe(true);
      expect(suffixEl.tagName.toLowerCase()).toBe('span');
    });

    it('does not render suffix when absent', () => {
      const { container } = render(StatusBadge, { props: { status: 'Running' } });
      const badge = container.querySelector('.badge');
      expect(badge?.querySelectorAll('span')).toHaveLength(0);
    });
  });
});
