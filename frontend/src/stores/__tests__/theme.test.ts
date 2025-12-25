import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';

// Mock the dynamic imports before importing the theme module
vi.mock('../../lib/user-settings', () => ({
  saveUserSettings: vi.fn().mockResolvedValue(true),
}));

vi.mock('../auth', () => ({
  isAuthenticated: {
    subscribe: vi.fn((fn) => {
      fn(false);
      return () => {};
    }),
  },
}));

describe('theme store', () => {
  let localStorageData: Record<string, string> = {};

  beforeEach(async () => {
    // Reset localStorage mock
    localStorageData = {};
    vi.mocked(localStorage.getItem).mockImplementation((key: string) => localStorageData[key] ?? null);
    vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => {
      localStorageData[key] = value;
    });

    // Reset document mock
    document.documentElement.classList.remove('dark');

    // Clear module cache to reset store state
    vi.resetModules();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('defaults to auto when no stored value', async () => {
      const { theme } = await import('../theme');
      expect(get(theme)).toBe('auto');
    });

    it('loads stored theme from localStorage', async () => {
      localStorageData['app-theme'] = 'dark';
      const { theme } = await import('../theme');
      expect(get(theme)).toBe('dark');
    });

    it('ignores invalid stored values', async () => {
      localStorageData['app-theme'] = 'invalid';
      const { theme } = await import('../theme');
      expect(get(theme)).toBe('auto');
    });

    it('accepts light theme from storage', async () => {
      localStorageData['app-theme'] = 'light';
      const { theme } = await import('../theme');
      expect(get(theme)).toBe('light');
    });
  });

  describe('theme.set', () => {
    it('updates the store value', async () => {
      const { theme } = await import('../theme');
      theme.set('dark');
      expect(get(theme)).toBe('dark');
    });

    it('persists to localStorage', async () => {
      const { theme } = await import('../theme');
      theme.set('dark');
      expect(localStorage.setItem).toHaveBeenCalledWith('app-theme', 'dark');
    });

    it('applies dark class when set to dark', async () => {
      const { theme } = await import('../theme');
      theme.set('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('removes dark class when set to light', async () => {
      document.documentElement.classList.add('dark');
      const { theme } = await import('../theme');
      theme.set('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);
    });
  });

  describe('toggleTheme', () => {
    it('cycles from light to dark', async () => {
      localStorageData['app-theme'] = 'light';
      const { theme, toggleTheme } = await import('../theme');

      toggleTheme();
      expect(get(theme)).toBe('dark');
    });

    it('cycles from dark to auto', async () => {
      localStorageData['app-theme'] = 'dark';
      const { theme, toggleTheme } = await import('../theme');

      toggleTheme();
      expect(get(theme)).toBe('auto');
    });

    it('cycles from auto to light', async () => {
      const { theme, toggleTheme } = await import('../theme');
      // Default is auto
      toggleTheme();
      expect(get(theme)).toBe('light');
    });

    it('completes full cycle', async () => {
      const { theme, toggleTheme } = await import('../theme');

      expect(get(theme)).toBe('auto');
      toggleTheme();
      expect(get(theme)).toBe('light');
      toggleTheme();
      expect(get(theme)).toBe('dark');
      toggleTheme();
      expect(get(theme)).toBe('auto');
    });
  });

  describe('setTheme', () => {
    it('sets theme to specified value', async () => {
      const { theme, setTheme } = await import('../theme');

      setTheme('dark');
      expect(get(theme)).toBe('dark');

      setTheme('light');
      expect(get(theme)).toBe('light');

      setTheme('auto');
      expect(get(theme)).toBe('auto');
    });

    it('persists to localStorage', async () => {
      const { setTheme } = await import('../theme');
      setTheme('dark');
      expect(localStorage.setItem).toHaveBeenCalledWith('app-theme', 'dark');
    });
  });

  describe('setThemeLocal', () => {
    it('updates store without triggering server save', async () => {
      const { theme, setThemeLocal } = await import('../theme');

      setThemeLocal('dark');
      expect(get(theme)).toBe('dark');
      expect(localStorage.setItem).toHaveBeenCalledWith('app-theme', 'dark');
    });

    it('applies theme to DOM', async () => {
      const { setThemeLocal } = await import('../theme');

      setThemeLocal('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);

      setThemeLocal('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);
    });
  });

  describe('auto theme', () => {
    it('applies light when system prefers light', async () => {
      vi.mocked(matchMedia).mockImplementation((query: string) => ({
        matches: false, // Not dark
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }));

      const { theme } = await import('../theme');
      theme.set('auto');

      expect(document.documentElement.classList.contains('dark')).toBe(false);
    });

    it('applies dark when system prefers dark', async () => {
      vi.mocked(matchMedia).mockImplementation((query: string) => ({
        matches: query === '(prefers-color-scheme: dark)', // Is dark
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }));

      vi.resetModules();
      const { theme } = await import('../theme');
      theme.set('auto');

      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
  });

  describe('subscription', () => {
    it('notifies subscribers on change', async () => {
      const { theme } = await import('../theme');
      const values: string[] = [];

      const unsubscribe = theme.subscribe((value) => {
        values.push(value);
      });

      theme.set('dark');
      theme.set('light');

      expect(values).toContain('dark');
      expect(values).toContain('light');

      unsubscribe();
    });
  });
});
