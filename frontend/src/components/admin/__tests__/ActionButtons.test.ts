import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import type { Component } from 'svelte';
import ActionButtons from '$components/admin/ActionButtons.svelte';

const MockIcon: Component = (() => ({})) as unknown as Component;

function makeAction(overrides: Record<string, unknown> = {}) {
  return {
    icon: MockIcon,
    label: 'Test Action',
    onclick: vi.fn(),
    ...overrides,
  };
}

describe('ActionButtons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('variants', () => {
    it('icon-only (default): renders button without visible label, with title', () => {
      render(ActionButtons, { props: { actions: [makeAction()] } });
      const btn = screen.getByRole('button');
      expect(btn).not.toHaveTextContent('Test Action');
      expect(btn).toHaveAttribute('title', 'Test Action');
    });

    it.each([
      { variant: 'with-text' as const, label: 'with-text' },
      { variant: 'mobile' as const, label: 'mobile' },
    ])('$label: renders button with visible label text', ({ variant }) => {
      render(ActionButtons, {
        props: { actions: [makeAction()], variant },
      });
      expect(screen.getByRole('button')).toHaveTextContent('Test Action');
    });

    it('mobile: buttons have flex-1 for full width', () => {
      render(ActionButtons, {
        props: { actions: [makeAction()], variant: 'mobile' },
      });
      expect(screen.getByRole('button').classList.contains('flex-1')).toBe(true);
    });
  });

  describe('color classes', () => {
    it.each([
      { color: 'primary', expectedClass: 'text-primary' },
      { color: 'success', expectedClass: 'text-green-600' },
      { color: 'danger', expectedClass: 'text-red-600' },
      { color: 'warning', expectedClass: 'text-yellow-600' },
      { color: 'info', expectedClass: 'text-blue-600' },
      { color: undefined, expectedClass: 'text-fg-muted' },
    ])('applies $expectedClass for color=$color', ({ color, expectedClass }) => {
      render(ActionButtons, {
        props: { actions: [makeAction({ color })] },
      });
      expect(screen.getByRole('button').className).toContain(expectedClass);
    });
  });

  describe('disabled state', () => {
    it('sets disabled attribute and opacity class', () => {
      render(ActionButtons, {
        props: { actions: [makeAction({ disabled: true })] },
      });
      const btn = screen.getByRole('button');
      expect(btn).toBeDisabled();
      expect(btn.className).toContain('opacity-50');
    });

    it('does not fire onclick when disabled', async () => {
      const onclick = vi.fn();
      render(ActionButtons, {
        props: { actions: [makeAction({ disabled: true, onclick })] },
      });
      await user.click(screen.getByRole('button'));
      expect(onclick).not.toHaveBeenCalled();
    });
  });

  it('fires onclick when clicked', async () => {
    const onclick = vi.fn();
    render(ActionButtons, {
      props: { actions: [makeAction({ onclick })] },
    });
    await user.click(screen.getByRole('button'));
    expect(onclick).toHaveBeenCalledOnce();
  });

  describe('title attribute', () => {
    it.each([
      { title: 'Custom Title', expected: 'Custom Title', desc: 'uses explicit title' },
      { title: undefined, expected: 'Test Action', desc: 'falls back to label' },
    ])('$desc', ({ title, expected }) => {
      render(ActionButtons, {
        props: { actions: [makeAction({ title })] },
      });
      expect(screen.getByRole('button')).toHaveAttribute('title', expected);
    });
  });

  it('renders N buttons for N actions', () => {
    const actions = [makeAction({ label: 'A' }), makeAction({ label: 'B' }), makeAction({ label: 'C' })];
    render(ActionButtons, { props: { actions } });
    expect(screen.getAllByRole('button')).toHaveLength(3);
  });
});
