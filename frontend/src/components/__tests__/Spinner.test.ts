import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Spinner from '../Spinner.svelte';

describe('Spinner', () => {
  const getSpinner = () => screen.getByRole('status');

  describe('rendering', () => {
    it('renders an accessible SVG spinner', () => {
      render(Spinner);
      const svg = getSpinner();
      expect(svg).toBeInTheDocument();
      expect(svg.tagName.toLowerCase()).toBe('svg');
      expect(svg).toHaveAttribute('aria-label', 'Loading');
      expect(svg.classList.contains('animate-spin')).toBe(true);
    });
  });

  describe('size prop', () => {
    it.each([
      { size: 'small', heightClass: 'h-4', widthClass: 'w-4' },
      { size: 'medium', heightClass: 'h-6', widthClass: 'w-6' },
      { size: 'large', heightClass: 'h-8', widthClass: 'w-8' },
      { size: 'xlarge', heightClass: 'h-12', widthClass: 'w-12' },
    ] as const)('applies $heightClass/$widthClass for size="$size"', ({ size, heightClass, widthClass }) => {
      render(Spinner, { props: { size } });
      const svg = getSpinner();
      expect(svg.classList.contains(heightClass)).toBe(true);
      expect(svg.classList.contains(widthClass)).toBe(true);
    });

    it('defaults to medium size', () => {
      render(Spinner);
      const svg = getSpinner();
      expect(svg.classList.contains('h-6')).toBe(true);
      expect(svg.classList.contains('w-6')).toBe(true);
    });
  });

  describe('color prop', () => {
    it.each([
      { color: 'primary', expectedClass: 'text-primary' },
      { color: 'white', expectedClass: 'text-white' },
      { color: 'current', expectedClass: 'text-current' },
      { color: 'muted', expectedClass: 'text-gray-400' },
    ] as const)('applies $expectedClass for color="$color"', ({ color, expectedClass }) => {
      render(Spinner, { props: { color } });
      expect(getSpinner().classList.contains(expectedClass)).toBe(true);
    });

    it('defaults to primary color', () => {
      render(Spinner);
      expect(getSpinner().classList.contains('text-primary')).toBe(true);
    });
  });

  describe('className prop', () => {
    it('applies and combines custom className with defaults', () => {
      render(Spinner, { props: { className: 'my-spinner', size: 'large' } });
      const svg = getSpinner();
      expect(svg.classList.contains('my-spinner')).toBe(true);
      expect(svg.classList.contains('animate-spin')).toBe(true);
      expect(svg.classList.contains('h-8')).toBe(true);
    });
  });

  describe('SVG structure', () => {
    it('contains required SVG elements with correct viewBox', () => {
      render(Spinner);
      const svg = getSpinner();
      expect(svg.querySelector('circle')).toBeInTheDocument();
      expect(svg.querySelector('path')).toBeInTheDocument();
      expect(svg.getAttribute('viewBox')).toBe('0 0 24 24');
    });
  });

  describe('fallback behavior for invalid props', () => {
    it('falls back to medium size for invalid size value', () => {
      // @ts-expect-error - intentionally passing invalid value to test fallback
      render(Spinner, { props: { size: 'invalid-size' } });
      const svg = getSpinner();
      // Should fall back to medium (h-6 w-6)
      expect(svg.classList.contains('h-6')).toBe(true);
      expect(svg.classList.contains('w-6')).toBe(true);
    });

    it('falls back to primary color for invalid color value', () => {
      // @ts-expect-error - intentionally passing invalid value to test fallback
      render(Spinner, { props: { color: 'invalid-color' } });
      const svg = getSpinner();
      // Should fall back to primary
      expect(svg.classList.contains('text-primary')).toBe(true);
    });

    it('handles both invalid size and color gracefully', () => {
      // @ts-expect-error - intentionally passing invalid values to test fallback
      render(Spinner, { props: { size: 'unknown', color: 'unknown' } });
      const svg = getSpinner();
      // Should fall back to defaults
      expect(svg.classList.contains('h-6')).toBe(true);
      expect(svg.classList.contains('w-6')).toBe(true);
      expect(svg.classList.contains('text-primary')).toBe(true);
    });
  });
});
