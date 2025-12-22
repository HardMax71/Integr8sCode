import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Spinner from '../Spinner.svelte';

describe('Spinner', () => {
  describe('rendering', () => {
    it('renders an SVG element', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      expect(svg).toBeInTheDocument();
      expect(svg.tagName.toLowerCase()).toBe('svg');
    });

    it('has accessible label', () => {
      render(Spinner);

      const spinner = screen.getByLabelText('Loading');
      expect(spinner).toBeInTheDocument();
    });

    it('has animate-spin class', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('animate-spin')).toBe(true);
    });
  });

  describe('size prop', () => {
    it('applies small size class', () => {
      render(Spinner, { props: { size: 'small' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('h-4')).toBe(true);
      expect(svg.classList.contains('w-4')).toBe(true);
    });

    it('applies medium size class by default', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('h-6')).toBe(true);
      expect(svg.classList.contains('w-6')).toBe(true);
    });

    it('applies large size class', () => {
      render(Spinner, { props: { size: 'large' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('h-8')).toBe(true);
      expect(svg.classList.contains('w-8')).toBe(true);
    });

    it('applies xlarge size class', () => {
      render(Spinner, { props: { size: 'xlarge' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('h-12')).toBe(true);
      expect(svg.classList.contains('w-12')).toBe(true);
    });
  });

  describe('color prop', () => {
    it('applies primary color by default', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('text-primary')).toBe(true);
    });

    it('applies white color class', () => {
      render(Spinner, { props: { color: 'white' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('text-white')).toBe(true);
    });

    it('applies current color class', () => {
      render(Spinner, { props: { color: 'current' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('text-current')).toBe(true);
    });

    it('applies muted color class', () => {
      render(Spinner, { props: { color: 'muted' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('text-gray-400')).toBe(true);
    });
  });

  describe('className prop', () => {
    it('applies custom className', () => {
      render(Spinner, { props: { className: 'custom-class' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('custom-class')).toBe(true);
    });

    it('combines with default classes', () => {
      render(Spinner, { props: { className: 'my-spinner', size: 'large' } });

      const svg = screen.getByRole('status');
      expect(svg.classList.contains('my-spinner')).toBe(true);
      expect(svg.classList.contains('animate-spin')).toBe(true);
      expect(svg.classList.contains('h-8')).toBe(true);
    });
  });

  describe('SVG structure', () => {
    it('contains circle element', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      const circle = svg.querySelector('circle');
      expect(circle).toBeInTheDocument();
    });

    it('contains path element', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      const path = svg.querySelector('path');
      expect(path).toBeInTheDocument();
    });

    it('has correct viewBox', () => {
      render(Spinner);

      const svg = screen.getByRole('status');
      expect(svg.getAttribute('viewBox')).toBe('0 0 24 24');
    });
  });
});
