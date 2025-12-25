import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

const mockGetUserSettings = vi.fn();
const mockUpdateUserSettings = vi.fn();

vi.mock('../api', () => ({
  getUserSettingsApiV1UserSettingsGet: (...args: unknown[]) => mockGetUserSettings(...args),
  updateUserSettingsApiV1UserSettingsPut: (...args: unknown[]) => mockUpdateUserSettings(...args),
}));

const mockSetUserSettings = vi.fn();
const mockUpdateSettings = vi.fn();

vi.mock('../../stores/userSettings', () => ({
  setUserSettings: (settings: unknown) => mockSetUserSettings(settings),
  updateSettings: (partial: unknown) => mockUpdateSettings(partial),
}));

const mockSetThemeLocal = vi.fn();

vi.mock('../../stores/theme', () => ({
  setThemeLocal: (theme: string) => mockSetThemeLocal(theme),
}));

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
    mockGetUserSettings.mockReset();
    mockUpdateUserSettings.mockReset();
    mockSetUserSettings.mockReset();
    mockUpdateSettings.mockReset();
    mockSetThemeLocal.mockReset();

    mockIsAuthenticated = true;

    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});

    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('loadUserSettings', () => {
    it('fetches from API', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: { theme: 'light', editor: {} },
        error: null
      });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockGetUserSettings).toHaveBeenCalledWith({});
    });

    it('updates store with API response', async () => {
      const apiSettings = { theme: 'system', editor: { tab_size: 4 } };
      mockGetUserSettings.mockResolvedValue({ data: apiSettings, error: null });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetUserSettings).toHaveBeenCalledWith(apiSettings);
    });

    it('applies theme from API response', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: { theme: 'dark' },
        error: null
      });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetThemeLocal).toHaveBeenCalledWith('dark');
    });

    it('returns undefined on API error', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: null,
        error: { detail: 'Not found' }
      });

      const { loadUserSettings } = await import('../user-settings');
      const result = await loadUserSettings();

      expect(result).toBeUndefined();
    });

    it('returns undefined on network error', async () => {
      mockGetUserSettings.mockRejectedValue(new Error('Network error'));

      const { loadUserSettings } = await import('../user-settings');
      const result = await loadUserSettings();

      expect(result).toBeUndefined();
    });

    it('does not apply theme when not in settings', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: { editor: {} },
        error: null
      });

      const { loadUserSettings } = await import('../user-settings');
      await loadUserSettings();

      expect(mockSetThemeLocal).not.toHaveBeenCalled();
    });
  });

  describe('saveUserSettings', () => {
    it('returns false when not authenticated', async () => {
      mockIsAuthenticated = false;
      vi.resetModules();

      const { saveUserSettings } = await import('../user-settings');
      const result = await saveUserSettings({ theme: 'dark' });

      expect(result).toBe(false);
      expect(mockUpdateUserSettings).not.toHaveBeenCalled();
    });

    it('calls API with partial settings', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('../user-settings');
      await saveUserSettings({ theme: 'dark' });

      expect(mockUpdateUserSettings).toHaveBeenCalledWith({
        body: { theme: 'dark' }
      });
    });

    it('can save editor settings', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });
      const editorSettings = { font_size: 16, tab_size: 2 };

      const { saveUserSettings } = await import('../user-settings');
      await saveUserSettings({ editor: editorSettings });

      expect(mockUpdateUserSettings).toHaveBeenCalledWith({
        body: { editor: editorSettings }
      });
    });

    it('can save multiple settings at once', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('../user-settings');
      await saveUserSettings({ theme: 'dark', editor: { font_size: 18 } });

      expect(mockUpdateUserSettings).toHaveBeenCalledWith({
        body: { theme: 'dark', editor: { font_size: 18 } }
      });
    });

    it('updates store on success', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('../user-settings');
      await saveUserSettings({ theme: 'system' });

      expect(mockUpdateSettings).toHaveBeenCalledWith({ theme: 'system' });
    });

    it('applies theme locally when theme is saved', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('../user-settings');
      await saveUserSettings({ theme: 'dark' });

      expect(mockSetThemeLocal).toHaveBeenCalledWith('dark');
    });

    it('does not apply theme when only editor settings saved', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('../user-settings');
      await saveUserSettings({ editor: { font_size: 16 } });

      expect(mockSetThemeLocal).not.toHaveBeenCalled();
    });

    it('returns true on success', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('../user-settings');
      const result = await saveUserSettings({ theme: 'light' });

      expect(result).toBe(true);
    });

    it('returns false on API error', async () => {
      mockUpdateUserSettings.mockResolvedValue({
        data: null,
        error: { detail: 'Server error' }
      });

      const { saveUserSettings } = await import('../user-settings');
      const result = await saveUserSettings({ theme: 'dark' });

      expect(result).toBe(false);
    });

    it('returns false on network error', async () => {
      mockUpdateUserSettings.mockRejectedValue(new Error('Network error'));

      const { saveUserSettings } = await import('../user-settings');
      const result = await saveUserSettings({ theme: 'dark' });

      expect(result).toBe(false);
    });
  });
});
