import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import FilterPanelWrapper from './FilterPanelWrapper.svelte';

describe('FilterPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('toggle button', () => {
    it('renders toggle button by default', () => {
      render(FilterPanelWrapper);
      expect(screen.getByRole('button', { name: /Filters/i })).toBeInTheDocument();
    });

    it('hides toggle button when showToggleButton=false', () => {
      render(FilterPanelWrapper, { props: { showToggleButton: false } });
      expect(screen.queryByRole('button', { name: /Filters/i })).not.toBeInTheDocument();
    });

    it('flips open and fires onToggle on click', async () => {
      const onToggle = vi.fn();
      render(FilterPanelWrapper, { props: { onToggle } });
      await user.click(screen.getByRole('button', { name: /Filters/i }));
      expect(onToggle).toHaveBeenCalledOnce();
      expect(screen.getByTestId('filter-content')).toBeInTheDocument();
    });
  });

  describe('active filter badge', () => {
    it.each([
      { hasActiveFilters: true, visible: true },
      { hasActiveFilters: false, visible: false },
    ])('badge visible=$visible when hasActiveFilters=$hasActiveFilters', ({ hasActiveFilters, visible }) => {
      render(FilterPanelWrapper, {
        props: { hasActiveFilters, activeFilterCount: 3 },
      });
      if (visible) {
        expect(screen.getByText('3')).toBeInTheDocument();
      } else {
        expect(screen.queryByText('3')).not.toBeInTheDocument();
      }
    });
  });

  describe('panel content', () => {
    it.each([
      { open: true, visible: true },
      { open: false, visible: false },
    ])('children visible=$visible when open=$open', ({ open, visible }) => {
      render(FilterPanelWrapper, { props: { open } });
      if (visible) {
        expect(screen.getByTestId('filter-content')).toBeInTheDocument();
      } else {
        expect(screen.queryByTestId('filter-content')).not.toBeInTheDocument();
      }
    });
  });

  describe('title', () => {
    it.each([
      { title: undefined, expected: 'Filter' },
      { title: 'Advanced', expected: 'Advanced' },
    ])('renders "$expected" when title=$title', ({ title, expected }) => {
      render(FilterPanelWrapper, { props: { open: true, title } });
      expect(screen.getByText(expected)).toBeInTheDocument();
    });
  });

  describe('action buttons', () => {
    it.each([
      { button: 'Clear All', callbackProp: 'onClear' },
      { button: 'Apply', callbackProp: 'onApply' },
    ] as const)('$button: visible only when $callbackProp provided, fires callback', async ({ button, callbackProp }) => {
      // Hidden when no callback
      render(FilterPanelWrapper, { props: { open: true } });
      expect(screen.queryByRole('button', { name: new RegExp(button, 'i') })).not.toBeInTheDocument();

      // Visible and fires callback
      const callback = vi.fn();
      const { unmount } = render(FilterPanelWrapper, {
        props: { open: true, [callbackProp]: callback },
      });
      const btn = screen.getByRole('button', { name: new RegExp(button, 'i') });
      expect(btn).toBeInTheDocument();
      await user.click(btn);
      expect(callback).toHaveBeenCalledOnce();
      unmount();
    });
  });
});
