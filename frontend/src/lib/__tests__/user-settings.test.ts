import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// Mock the API functions
const mockGetUserSettings = vi.fn();
const mockUpdateTheme = vi.fn();
const mockUpdateEditorSettings = vi.fn();

vi.mock('../api', () => ({
  getUserSettingsApiV1UserSettingsGet: (...args: unknown[]) => mockGetUserSettings(...args),
  updateThemeApiV1UserSettingsThemePut: (...args: unknown[]) => mockUpdateTheme(...args),
  updateEditorSettingsApiV1UserSettingsEditorPut: (...args: unknown[]) => mockUpdateEditorSettings(...args),
}));

// Mock the settings-cache module
const mockGetCachedSettings = vi.fn();
const mockSetCachedSettings = vi.fn();
const mockUpdateCachedSetting = vi.fn();

vi.mock('../settings-cache', () => ({
  getCachedSettings: () => mockGetCachedSettings(),
  setCachedSettings: (settings: unknown) => mockSetCachedSettings(settings),
  updateCachedSetting: (path: string, value: unknown) => mockUpdateCachedSetting(path, value),
}));

// Mock the theme store
const mockSetThemeLocal = vi.fn();

vi.mock('../../stores/theme', () => ({
  setThemeLocal: (theme: string) => mockSetThemeLocal(theme),
}));

// Mock the auth store
let mockIsAuthenticated = true;

vi.mock('../../stores/auth', () => ({
  isAuthenticated: {
    subscribe: (fn: (value: boolean) => void) => {
      fn(mockIsAuthenticated);
      return () => {};
    },
  },
}));

describe('user-settings', () => {
  beforeEach(async () => {
    // Reset all mocks
    mockGetUserSettings.mockReset();
    mockUpdateTheme.mockReset();
    mockUpdateEditorSettings.mockReset();
    mockGetCachedSettings.mockReset();
    mockSetCachedSettings.mockReset();
    mockUpdateCachedSetting.mockReset();
    mockSetThemeLocal.mockReset();

    // Default to authenticated
    mockIsAuthenticated = true;

    // Suppress console output
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});

    // Clear module cache
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('saveThemeSetting', () => {
    it('returns undefined when not authenticated', async () => {
      mockIsAuthenticated = false;
      vi.resetModules();

      const { saveThemeSetting } = await import('../user-settings');
      const result = await saveThemeSetting('dark');

      expect(result).toBeUndefined();
      expect(mockUpdateTheme).not.toHaveBeenCalled();
    });

    it('calls API with correct theme', async () => {
      mockUpdateTheme.mockResolvedValue({ data: {}, error: null });

      const { saveThemeSetting } = await import('../user-settings');
      await saveThemeSetting('dark');

      expect(mockUpdateTheme).toHaveBeenCalledWith({
        body: { theme: 'dark' }
      });
    });

    it('updates cache on success', async () => {
      mockUpdateTheme.mockResolvedValue({ data: {}, error: null });

      const { saveThemeSetting } = await import('../user-settings');
      await saveThemeSetting('system');

      expect(mockUpdateCachedSetting).toHaveBeenCalledWith('theme', 'system');
    });

    it('returns true on success', async () => {
      mockUpdateTheme.mockResolvedValue({ data: {}, error: null });

      const { saveThemeSetting } = await import('../user-settings');
      const result = await saveThemeSetting('light');

      expect(result).toBe(true);
    });

    it('returns false on API error', async () => {
      mockUpdateTheme.mockResolvedValue({ data: null, error: { detail: 'Server error' } });

      const { saveThemeSetting } = await import('../user-settings');
      const result = await saveThemeSetting('dark');

      expect(result).toBe(false);
    });

    it('returns false on network error', async () => {
      mockUpdateTheme.mockRejectedValue(new Error('Network error'));

      const { saveThemeSetting } = await import('../user-settings');
      const result = await saveThemeSetting('dark');

      expect(result).toBe(false);
    });
  });

  describe('loadUserSettings', () => {
    it('returns cached settings if available', async () => {
      const cachedSettings = { theme: 'dark', editor: { fontSize: 14 } };
      mockGetCachedSettings.mockReturnValue(cachedSettings);

      const { loadUserSettings } = await import('../user-settings');
      const result = await loadUserSettings();

      expect(result).toEqual(cachedSettings);
      expect(mockGetUserSettings).not.toHaveBeenCalled();
    });

    it('applies cached theme', async () => {
      const cachedSettings = { theme: 'dark' };
      mockGetCachedSettings.mockReturnValue(cachedSettings);

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetThemeLocal).toHaveBeenCalledWith('dark');
    });

    it('fetches from API when no cache', async () => {
      mockGetCachedSettings.mockReturnValue(null);
      mockGetUserSettings.mockResolvedValue({
        data: { theme: 'light', editor: {} },
        error: null
      });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockGetUserSettings).toHaveBeenCalledWith({});
    });

    it('caches API response', async () => {
      const apiSettings = { theme: 'system', editor: { tabSize: 4 } };
      mockGetCachedSettings.mockReturnValue(null);
      mockGetUserSettings.mockResolvedValue({ data: apiSettings, error: null });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetCachedSettings).toHaveBeenCalledWith(apiSettings);
    });

    it('applies theme from API response', async () => {
      mockGetCachedSettings.mockReturnValue(null);
      mockGetUserSettings.mockResolvedValue({
        data: { theme: 'dark' },
        error: null
      });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetThemeLocal).toHaveBeenCalledWith('dark');
    });

    it('returns undefined on API error', async () => {
      mockGetCachedSettings.mockReturnValue(null);
      mockGetUserSettings.mockResolvedValue({
        data: null,
        error: { detail: 'Not found' }
      });

      const { loadUserSettings } = await import('../user-settings');
      const result = await loadUserSettings();

      expect(result).toBeUndefined();
    });

    it('returns undefined on network error', async () => {
      mockGetCachedSettings.mockReturnValue(null);
      mockGetUserSettings.mockRejectedValue(new Error('Network error'));

      const { loadUserSettings } = await import('../user-settings');
      const result = await loadUserSettings();

      expect(result).toBeUndefined();
    });

    it('does not apply theme when not in settings', async () => {
      mockGetCachedSettings.mockReturnValue({ editor: {} });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetThemeLocal).not.toHaveBeenCalled();
    });
  });

  describe('saveEditorSettings', () => {
    it('returns undefined when not authenticated', async () => {
      mockIsAuthenticated = false;
      vi.resetModules();

      const { saveEditorSettings } = await import('../user-settings');
      const result = await saveEditorSettings({ fontSize: 14 } as any);

      expect(result).toBeUndefined();
      expect(mockUpdateEditorSettings).not.toHaveBeenCalled();
    });

    it('calls API with editor settings', async () => {
      mockUpdateEditorSettings.mockResolvedValue({ data: {}, error: null });
      const editorSettings = { fontSize: 16, tabSize: 2, theme: 'monokai' };

      const { saveEditorSettings } = await import('../user-settings');
      await saveEditorSettings(editorSettings as any);

      expect(mockUpdateEditorSettings).toHaveBeenCalledWith({
        body: editorSettings
      });
    });

    it('updates cache on success', async () => {
      mockUpdateEditorSettings.mockResolvedValue({ data: {}, error: null });
      const editorSettings = { fontSize: 18 };

      const { saveEditorSettings } = await import('../user-settings');
      await saveEditorSettings(editorSettings as any);

      expect(mockUpdateCachedSetting).toHaveBeenCalledWith('editor', editorSettings);
    });

    it('returns true on success', async () => {
      mockUpdateEditorSettings.mockResolvedValue({ data: {}, error: null });

      const { saveEditorSettings } = await import('../user-settings');
      const result = await saveEditorSettings({ fontSize: 14 } as any);

      expect(result).toBe(true);
    });

    it('returns false on API error', async () => {
      mockUpdateEditorSettings.mockResolvedValue({
        data: null,
        error: { detail: 'Invalid settings' }
      });

      const { saveEditorSettings } = await import('../user-settings');
      const result = await saveEditorSettings({ fontSize: 14 } as any);

      expect(result).toBe(false);
    });

    it('returns false on network error', async () => {
      mockUpdateEditorSettings.mockRejectedValue(new Error('Network error'));

      const { saveEditorSettings } = await import('../user-settings');
      const result = await saveEditorSettings({ fontSize: 14 } as any);

      expect(result).toBe(false);
    });
  });
});
