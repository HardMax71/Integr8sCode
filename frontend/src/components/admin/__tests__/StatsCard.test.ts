import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import type { Component } from 'svelte';
import StatsCard from '../StatsCard.svelte';

const MockIcon: Component = (() => ({})) as unknown as Component;

describe('StatsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    { label: 'Total', value: 42, desc: 'numeric' },
    { label: 'Status', value: 'Active', desc: 'string' },
  ])('renders label and $desc value', ({ label, value }) => {
    render(StatsCard, { props: { label, value } });
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(String(value))).toBeInTheDocument();
  });

  describe('sublabel', () => {
    it('shows sublabel when provided', () => {
      render(StatsCard, { props: { label: 'Total', value: 42, sublabel: '+5 today' } });
      expect(screen.getByText('+5 today')).toBeInTheDocument();
    });

    it('does not render sublabel when absent', () => {
      const { container } = render(StatsCard, { props: { label: 'Total', value: 42 } });
      expect(container.querySelectorAll('p')).toHaveLength(2);
    });
  });

  describe('icon', () => {
    it.each([
      { icon: MockIcon, pCount: 2, desc: 'renders without error when provided' },
      { icon: undefined, pCount: 2, desc: 'renders only label/value when absent' },
    ])('$desc', ({ icon, pCount }) => {
      const { container } = render(StatsCard, {
        props: { label: 'Total', value: 42, ...(icon ? { icon } : {}) },
      });
      expect(screen.getByText('Total')).toBeInTheDocument();
      expect(screen.getByText('42')).toBeInTheDocument();
      expect(container.querySelectorAll('p').length).toBeGreaterThanOrEqual(pCount);
    });
  });

  describe('compact mode', () => {
    it.each([
      { compact: true, selector: '.p-2' },
      { compact: false, selector: '.p-4' },
    ])('applies $selector padding when compact=$compact', ({ compact, selector }) => {
      const { container } = render(StatsCard, {
        props: { label: 'Total', value: 42, compact },
      });
      expect(container.querySelector(selector)).toBeInTheDocument();
    });
  });

  describe('custom colors', () => {
    it('applies bgColor class', () => {
      const { container } = render(StatsCard, {
        props: { label: 'Total', value: 42, bgColor: 'bg-green-100' },
      });
      expect(container.firstElementChild?.classList.contains('bg-green-100')).toBe(true);
    });

    it('applies textColor to value', () => {
      render(StatsCard, {
        props: { label: 'Total', value: 42, textColor: 'text-red-500' },
      });
      expect(screen.getByText('42').classList.contains('text-red-500')).toBe(true);
    });
  });
});
