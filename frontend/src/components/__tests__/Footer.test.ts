import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Footer from '../Footer.svelte';

describe('Footer', () => {
  let originalDate: DateConstructor;

  beforeEach(() => {
    // Mock Date to have consistent year in tests
    originalDate = global.Date;
    const mockDate = class extends Date {
      constructor() {
        super('2025-01-01T00:00:00.000Z');
      }
      static now() {
        return new originalDate('2025-01-01T00:00:00.000Z').getTime();
      }
    };
    vi.stubGlobal('Date', mockDate);
  });

  afterEach(() => {
    vi.stubGlobal('Date', originalDate);
  });

  describe('branding', () => {
    it('displays brand name', () => {
      render(Footer);

      expect(screen.getByRole('heading', { name: /Integr8sCode/i })).toBeInTheDocument();
    });

    it('displays tagline', () => {
      render(Footer);

      expect(screen.getByText(/Run code online with ease and security/i)).toBeInTheDocument();
    });
  });

  describe('navigation links', () => {
    it('displays Navigation section', () => {
      render(Footer);

      expect(screen.getByRole('heading', { name: /Navigation/i })).toBeInTheDocument();
    });

    it('has Home link', () => {
      render(Footer);

      const homeLink = screen.getByRole('link', { name: /^Home$/i });
      expect(homeLink).toBeInTheDocument();
      expect(homeLink.getAttribute('href')).toBe('/');
    });

    it('has Code Editor link', () => {
      render(Footer);

      const editorLink = screen.getByRole('link', { name: /Code Editor/i });
      expect(editorLink).toBeInTheDocument();
      expect(editorLink.getAttribute('href')).toBe('/editor');
    });
  });

  describe('tools and info section', () => {
    it('displays Tools & Info section', () => {
      render(Footer);

      expect(screen.getByRole('heading', { name: /Tools & Info/i })).toBeInTheDocument();
    });

    it('has Grafana link with external attributes', () => {
      render(Footer);

      const grafanaLink = screen.getByRole('link', { name: /Grafana/i });
      expect(grafanaLink).toBeInTheDocument();
      expect(grafanaLink.getAttribute('target')).toBe('_blank');
      expect(grafanaLink.getAttribute('rel')).toContain('noopener');
    });

    it('has Privacy Policy link', () => {
      render(Footer);

      const privacyLink = screen.getByRole('link', { name: /Privacy Policy/i });
      expect(privacyLink).toBeInTheDocument();
      expect(privacyLink.getAttribute('href')).toBe('/privacy');
    });
  });

  describe('social links', () => {
    it('has Telegram link with accessibility', () => {
      render(Footer);

      const telegramLink = screen.getByRole('link', { name: /Telegram/i });
      expect(telegramLink).toBeInTheDocument();
      expect(telegramLink.getAttribute('href')).toBe('https://t.me/MaxAzatian');
      expect(telegramLink.getAttribute('target')).toBe('_blank');
      expect(telegramLink.getAttribute('rel')).toContain('noopener');
    });

    it('has GitHub link with accessibility', () => {
      render(Footer);

      const githubLink = screen.getByRole('link', { name: /GitHub/i });
      expect(githubLink).toBeInTheDocument();
      expect(githubLink.getAttribute('href')).toBe('https://github.com/HardMax71/Integr8sCode');
      expect(githubLink.getAttribute('target')).toBe('_blank');
      expect(githubLink.getAttribute('rel')).toContain('noopener');
    });

    it('has screen reader text for social icons', () => {
      render(Footer);

      // Check for sr-only spans
      expect(screen.getByText('Telegram', { selector: '.sr-only' })).toBeInTheDocument();
      expect(screen.getByText('GitHub', { selector: '.sr-only' })).toBeInTheDocument();
    });
  });

  describe('copyright', () => {
    it('displays current year', () => {
      render(Footer);

      expect(screen.getByText(/© 2025 Integr8sCode/)).toBeInTheDocument();
    });

    it('credits the author', () => {
      render(Footer);

      expect(screen.getByText(/Max Azatian/)).toBeInTheDocument();
    });

    it('includes rights reserved text', () => {
      render(Footer);

      expect(screen.getByText(/All rights reserved/)).toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('uses semantic footer element', () => {
      const { container } = render(Footer);

      expect(container.querySelector('footer')).toBeInTheDocument();
    });

    it('has proper heading hierarchy', () => {
      render(Footer);

      const h2 = screen.getByRole('heading', { level: 2 });
      expect(h2).toHaveTextContent('Integr8sCode');

      const h3s = screen.getAllByRole('heading', { level: 3 });
      expect(h3s.length).toBeGreaterThanOrEqual(2);
    });

    it('all external links have noopener noreferrer', () => {
      render(Footer);

      const externalLinks = screen.getAllByRole('link').filter(
        link => link.getAttribute('target') === '_blank'
      );

      externalLinks.forEach(link => {
        expect(link.getAttribute('rel')).toContain('noopener');
        expect(link.getAttribute('rel')).toContain('noreferrer');
      });
    });
  });

  describe('responsive design', () => {
    it('has responsive grid classes', () => {
      const { container } = render(Footer);

      const grid = container.querySelector('.grid');
      expect(grid).toBeInTheDocument();
      expect(grid?.classList.contains('md:grid-cols-12')).toBe(true);
    });
  });
});
