import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';

const CACHE_KEY = 'integr8scode-user-settings';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

describe('settings-cache', () => {
  let localStorageData: Record<string, string> = {};

  beforeEach(async () => {
    // Reset localStorage mock
    localStorageData = {};
    vi.mocked(localStorage.getItem).mockImplementation((key: string) => localStorageData[key] ?? null);
    vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => {
      localStorageData[key] = value;
    });
    vi.mocked(localStorage.removeItem).mockImplementation((key: string) => {
      delete localStorageData[key];
    });

    // Reset modules to get fresh store state
    vi.resetModules();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('getCachedSettings', () => {
    it('returns null when no cache exists', async () => {
      const { getCachedSettings } = await import('../settings-cache');
      expect(getCachedSettings()).toBe(null);
    });

    it('returns cached settings when valid', async () => {
      const settings = { theme: 'dark', editor: { fontSize: 14 } };
      localStorageData[CACHE_KEY] = JSON.stringify({
        data: settings,
        timestamp: Date.now()
      });

      const { getCachedSettings } = await import('../settings-cache');
      expect(getCachedSettings()).toEqual(settings);
    });

    it('returns null and clears cache when expired', async () => {
      const settings = { theme: 'light' };
      localStorageData[CACHE_KEY] = JSON.stringify({
        data: settings,
        timestamp: Date.now() - CACHE_TTL - 1000 // expired
      });

      const { getCachedSettings } = await import('../settings-cache');
      expect(getCachedSettings()).toBe(null);
      expect(localStorage.removeItem).toHaveBeenCalledWith(CACHE_KEY);
    });

    it('returns null and clears cache on parse error', async () => {
      localStorageData[CACHE_KEY] = 'invalid json{';
      vi.spyOn(console, 'error').mockImplementation(() => {});

      const { getCachedSettings } = await import('../settings-cache');
      expect(getCachedSettings()).toBe(null);
      expect(localStorage.removeItem).toHaveBeenCalledWith(CACHE_KEY);
    });
  });

  describe('setCachedSettings', () => {
    it('saves settings to localStorage', async () => {
      const { setCachedSettings } = await import('../settings-cache');
      const settings = { theme: 'dark', editor: { fontSize: 16 } };

      setCachedSettings(settings as any);

      expect(localStorage.setItem).toHaveBeenCalledWith(
        CACHE_KEY,
        expect.stringContaining('"theme":"dark"')
      );
    });

    it('updates the settingsCache store', async () => {
      const { setCachedSettings, settingsCache } = await import('../settings-cache');
      const settings = { theme: 'system', editor: { tabSize: 2 } };

      setCachedSettings(settings as any);

      expect(get(settingsCache)).toEqual(settings);
    });

    it('includes timestamp in cached data', async () => {
      const before = Date.now();
      const { setCachedSettings } = await import('../settings-cache');

      setCachedSettings({ theme: 'light' } as any);

      const saved = JSON.parse(localStorageData[CACHE_KEY]);
      expect(saved.timestamp).toBeGreaterThanOrEqual(before);
      expect(saved.timestamp).toBeLessThanOrEqual(Date.now());
    });

    it('handles localStorage errors gracefully', async () => {
      vi.mocked(localStorage.setItem).mockImplementation(() => {
        throw new Error('QuotaExceededError');
      });
      vi.spyOn(console, 'error').mockImplementation(() => {});

      const { setCachedSettings } = await import('../settings-cache');

      // Should not throw
      expect(() => setCachedSettings({ theme: 'dark' } as any)).not.toThrow();
    });
  });

  describe('clearCache', () => {
    it('removes settings from localStorage', async () => {
      localStorageData[CACHE_KEY] = JSON.stringify({ data: {}, timestamp: Date.now() });

      const { clearCache } = await import('../settings-cache');
      clearCache();

      expect(localStorage.removeItem).toHaveBeenCalledWith(CACHE_KEY);
    });

    it('sets settingsCache store to null', async () => {
      const { setCachedSettings, clearCache, settingsCache } = await import('../settings-cache');

      setCachedSettings({ theme: 'dark' } as any);
      expect(get(settingsCache)).not.toBe(null);

      clearCache();
      expect(get(settingsCache)).toBe(null);
    });
  });

  describe('updateCachedSetting', () => {
    it('does nothing when cache is empty', async () => {
      const { updateCachedSetting, settingsCache } = await import('../settings-cache');

      updateCachedSetting('theme', 'dark');

      expect(get(settingsCache)).toBe(null);
    });

    it('updates a top-level setting', async () => {
      const { setCachedSettings, updateCachedSetting, settingsCache } = await import('../settings-cache');

      setCachedSettings({ theme: 'light', editor: {} } as any);
      updateCachedSetting('theme', 'dark');

      expect(get(settingsCache)?.theme).toBe('dark');
    });

    it('updates a nested setting', async () => {
      const { setCachedSettings, updateCachedSetting, settingsCache } = await import('../settings-cache');

      setCachedSettings({ theme: 'light', editor: { fontSize: 12 } } as any);
      updateCachedSetting('editor.fontSize', 16);

      const current = get(settingsCache);
      expect((current as any)?.editor?.fontSize).toBe(16);
    });

    it('creates intermediate objects for deep paths', async () => {
      const { setCachedSettings, updateCachedSetting, settingsCache } = await import('../settings-cache');

      setCachedSettings({ theme: 'light' } as any);
      updateCachedSetting('editor.preferences.autoSave', true);

      const current = get(settingsCache) as any;
      expect(current?.editor?.preferences?.autoSave).toBe(true);
    });

    it('persists updated setting to localStorage', async () => {
      const { setCachedSettings, updateCachedSetting } = await import('../settings-cache');

      setCachedSettings({ theme: 'light' } as any);
      vi.mocked(localStorage.setItem).mockClear();

      updateCachedSetting('theme', 'dark');

      expect(localStorage.setItem).toHaveBeenCalledWith(
        CACHE_KEY,
        expect.stringContaining('"theme":"dark"')
      );
    });
  });

  describe('settingsCache store', () => {
    it('initializes from localStorage on module load', async () => {
      const settings = { theme: 'dark' };
      localStorageData[CACHE_KEY] = JSON.stringify({
        data: settings,
        timestamp: Date.now()
      });

      const { settingsCache } = await import('../settings-cache');

      expect(get(settingsCache)).toEqual(settings);
    });

    it('initializes to null when no cached settings', async () => {
      const { settingsCache } = await import('../settings-cache');
      expect(get(settingsCache)).toBe(null);
    });
  });
});
