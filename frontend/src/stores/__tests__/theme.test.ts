import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// Mock the dynamic imports before importing the theme module
vi.mock('../../lib/user-settings', () => ({
  saveUserSettings: vi.fn().mockResolvedValue(true),
}));

vi.mock('../auth.svelte', () => ({
  authStore: {
    isAuthenticated: false,
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
      const { themeStore } = await import('$stores/theme.svelte');
      expect(themeStore.value).toBe('auto');
    });

    it('loads stored theme from localStorage', async () => {
      localStorageData['app-theme'] = 'dark';
      const { themeStore } = await import('$stores/theme.svelte');
      expect(themeStore.value).toBe('dark');
    });

    it('ignores invalid stored values', async () => {
      localStorageData['app-theme'] = 'invalid';
      const { themeStore } = await import('$stores/theme.svelte');
      expect(themeStore.value).toBe('auto');
    });

    it('accepts light theme from storage', async () => {
      localStorageData['app-theme'] = 'light';
      const { themeStore } = await import('$stores/theme.svelte');
      expect(themeStore.value).toBe('light');
    });
  });

  describe('setTheme', () => {
    it('updates the store value', async () => {
      const { themeStore } = await import('$stores/theme.svelte');
      themeStore.setTheme('dark');
      expect(themeStore.value).toBe('dark');
    });

    it('persists to localStorage', async () => {
      const { themeStore } = await import('$stores/theme.svelte');
      themeStore.setTheme('dark');
      expect(localStorage.setItem).toHaveBeenCalledWith('app-theme', 'dark');
    });

    it('applies dark class when set to dark', async () => {
      const { themeStore } = await import('$stores/theme.svelte');
      themeStore.setTheme('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('removes dark class when set to light', async () => {
      document.documentElement.classList.add('dark');
      const { themeStore } = await import('$stores/theme.svelte');
      themeStore.setTheme('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);
    });
  });

  describe('toggleTheme', () => {
    it('cycles from light to dark', async () => {
      localStorageData['app-theme'] = 'light';
      const { themeStore } = await import('$stores/theme.svelte');

      themeStore.toggleTheme();
      expect(themeStore.value).toBe('dark');
    });

    it('cycles from dark to auto', async () => {
      localStorageData['app-theme'] = 'dark';
      const { themeStore } = await import('$stores/theme.svelte');

      themeStore.toggleTheme();
      expect(themeStore.value).toBe('auto');
    });

    it('cycles from auto to light', async () => {
      const { themeStore } = await import('$stores/theme.svelte');
      // Default is auto
      themeStore.toggleTheme();
      expect(themeStore.value).toBe('light');
    });

    it('completes full cycle', async () => {
      const { themeStore } = await import('$stores/theme.svelte');

      expect(themeStore.value).toBe('auto');
      themeStore.toggleTheme();
      expect(themeStore.value).toBe('light');
      themeStore.toggleTheme();
      expect(themeStore.value).toBe('dark');
      themeStore.toggleTheme();
      expect(themeStore.value).toBe('auto');
    });
  });

  describe('setTheme export', () => {
    it('sets theme to specified value', async () => {
      const { themeStore, setTheme } = await import('$stores/theme.svelte');

      setTheme('dark');
      expect(themeStore.value).toBe('dark');

      setTheme('light');
      expect(themeStore.value).toBe('light');

      setTheme('auto');
      expect(themeStore.value).toBe('auto');
    });

    it('persists to localStorage', async () => {
      const { setTheme } = await import('$stores/theme.svelte');
      setTheme('dark');
      expect(localStorage.setItem).toHaveBeenCalledWith('app-theme', 'dark');
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

      const { themeStore } = await import('$stores/theme.svelte');
      themeStore.setTheme('auto');

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
      const { themeStore } = await import('$stores/theme.svelte');
      themeStore.setTheme('auto');

      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
  });
});
