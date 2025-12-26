import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { updateMetaTags, pageMeta } from '$utils/meta';

describe('meta utilities', () => {
  let originalTitle: string;
  let metaDescription: HTMLMetaElement | null;

  beforeEach(() => {
    // Save original state
    originalTitle = document.title;
    metaDescription = document.querySelector('meta[name="description"]');

    // Reset document state
    document.title = 'Original Title';

    // Remove existing meta description if any
    const existingMeta = document.querySelector('meta[name="description"]');
    if (existingMeta) {
      existingMeta.remove();
    }
  });

  afterEach(() => {
    // Restore original state
    document.title = originalTitle;

    // Clean up any meta tags we created
    const testMeta = document.querySelector('meta[name="description"]');
    if (testMeta) {
      testMeta.remove();
    }

    // Restore original meta if it existed
    if (metaDescription) {
      document.head.appendChild(metaDescription);
    }
  });

  describe('updateMetaTags', () => {
    it('updates document title with suffix', () => {
      updateMetaTags('Test Page');

      expect(document.title).toBe('Test Page | Integr8sCode');
    });

    it('does not update title when not provided', () => {
      document.title = 'Keep This Title';

      updateMetaTags(undefined, 'Some description');

      expect(document.title).toBe('Keep This Title');
    });

    it('creates meta description if it does not exist', () => {
      expect(document.querySelector('meta[name="description"]')).toBe(null);

      updateMetaTags(undefined, 'New description');

      const meta = document.querySelector('meta[name="description"]');
      expect(meta).not.toBe(null);
      expect(meta?.getAttribute('content')).toBe('New description');
    });

    it('updates existing meta description', () => {
      // Create existing meta
      const existingMeta = document.createElement('meta');
      existingMeta.setAttribute('name', 'description');
      existingMeta.setAttribute('content', 'Old description');
      document.head.appendChild(existingMeta);

      updateMetaTags(undefined, 'Updated description');

      const meta = document.querySelector('meta[name="description"]');
      expect(meta?.getAttribute('content')).toBe('Updated description');
    });

    it('does not update description when not provided', () => {
      const existingMeta = document.createElement('meta');
      existingMeta.setAttribute('name', 'description');
      existingMeta.setAttribute('content', 'Keep this');
      document.head.appendChild(existingMeta);

      updateMetaTags('New Title');

      const meta = document.querySelector('meta[name="description"]');
      expect(meta?.getAttribute('content')).toBe('Keep this');
    });

    it('updates both title and description', () => {
      updateMetaTags('Full Update', 'Complete description');

      expect(document.title).toBe('Full Update | Integr8sCode');

      const meta = document.querySelector('meta[name="description"]');
      expect(meta?.getAttribute('content')).toBe('Complete description');
    });

    it('handles empty strings', () => {
      document.title = 'Original';

      updateMetaTags('', '');

      // Empty string is falsy, so title should not change
      expect(document.title).toBe('Original');
    });
  });

  describe('pageMeta', () => {
    it('contains home page meta', () => {
      expect(pageMeta.home).toBeDefined();
      expect(pageMeta.home.title).toBe('Home');
      expect(pageMeta.home.description).toContain('Integr8sCode');
    });

    it('contains editor page meta', () => {
      expect(pageMeta.editor).toBeDefined();
      expect(pageMeta.editor.title).toBe('Code Editor');
      expect(pageMeta.editor.description).toContain('code editor');
    });

    it('contains login page meta', () => {
      expect(pageMeta.login).toBeDefined();
      expect(pageMeta.login.title).toBe('Login');
      expect(pageMeta.login.description).toContain('Sign in');
    });

    it('contains register page meta', () => {
      expect(pageMeta.register).toBeDefined();
      expect(pageMeta.register.title).toBe('Register');
      expect(pageMeta.register.description).toContain('account');
    });

    it('all pages have title and description', () => {
      Object.entries(pageMeta).forEach(([key, meta]) => {
        expect(meta.title, `${key} should have title`).toBeDefined();
        expect(meta.title.length, `${key} title should not be empty`).toBeGreaterThan(0);
        expect(meta.description, `${key} should have description`).toBeDefined();
        expect(meta.description.length, `${key} description should not be empty`).toBeGreaterThan(0);
      });
    });

    it('can be used with updateMetaTags', () => {
      const { title, description } = pageMeta.home;

      updateMetaTags(title, description);

      expect(document.title).toBe('Home | Integr8sCode');

      const meta = document.querySelector('meta[name="description"]');
      expect(meta?.getAttribute('content')).toBe(description);
    });
  });
});
