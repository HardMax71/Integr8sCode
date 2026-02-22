import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

const mockGetUserSettings = vi.fn();
const mockUpdateUserSettings = vi.fn();

vi.mock('../api', () => ({
  getUserSettingsApiV1UserSettingsGet: (...args: unknown[]) => (mockGetUserSettings as (...a: unknown[]) => unknown)(...args),
  updateUserSettingsApiV1UserSettingsPut: (...args: unknown[]) => (mockUpdateUserSettings as (...a: unknown[]) => unknown)(...args),
}));

const mockSetUserSettings = vi.fn();

vi.mock('../../stores/userSettings.svelte', () => ({
  setUserSettings: (settings: unknown) => mockSetUserSettings(settings),
}));

const mockSetTheme = vi.fn();

vi.mock('../../stores/theme.svelte', () => ({
  setTheme: (theme: string) => mockSetTheme(theme),
}));

const mockAuthStore = {
  isAuthenticated: true as boolean | null,
};

vi.mock('../../stores/auth.svelte', () => ({
  authStore: mockAuthStore,
}));

vi.mock('../api-interceptors', () => ({}));

describe('user-settings', () => {
  beforeEach(async () => {
    mockGetUserSettings.mockReset();
    mockUpdateUserSettings.mockReset();
    mockSetUserSettings.mockReset();
    mockSetTheme.mockReset();

    mockAuthStore.isAuthenticated = true;

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

      const { loadUserSettings } = await import('$lib/user-settings');
      await loadUserSettings();

      expect(mockGetUserSettings).toHaveBeenCalledWith({});
    });

    it('updates store with API response', async () => {
      const apiSettings = { theme: 'system', editor: { tab_size: 4 } };
      mockGetUserSettings.mockResolvedValue({ data: apiSettings, error: null });

      const { loadUserSettings } = await import('$lib/user-settings');
      await loadUserSettings();

      expect(mockSetUserSettings).toHaveBeenCalledWith(apiSettings);
    });

    it('applies theme from API response', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: { theme: 'dark' },
        error: null
      });

      const { loadUserSettings } = await import('$lib/user-settings');
      await loadUserSettings();

      expect(mockSetTheme).toHaveBeenCalledWith('dark');
    });

    it('returns undefined on API error', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: null,
        error: { detail: 'Not found' }
      });

      const { loadUserSettings } = await import('$lib/user-settings');
      const result = await loadUserSettings();

      expect(result).toBeUndefined();
    });

    it('returns undefined on network error', async () => {
      mockGetUserSettings.mockResolvedValue({ data: undefined, error: new Error('Network error') });

      const { loadUserSettings } = await import('$lib/user-settings');
      const result = await loadUserSettings();

      expect(result).toBeUndefined();
    });

    it('always applies theme from response', async () => {
      mockGetUserSettings.mockResolvedValue({
        data: { theme: 'auto', editor: {} },
        error: null
      });

      const { loadUserSettings } = await import('$lib/user-settings');
      await loadUserSettings();

      expect(mockSetTheme).toHaveBeenCalledWith('auto');
    });
  });

  describe('saveUserSettings', () => {
    it('returns false when not authenticated', async () => {
      mockAuthStore.isAuthenticated = false;
      vi.resetModules();

      const { saveUserSettings } = await import('$lib/user-settings');
      const result = await saveUserSettings({ theme: 'dark' });

      expect(result).toBe(false);
      expect(mockUpdateUserSettings).not.toHaveBeenCalled();
    });

    it('calls API with partial settings', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('$lib/user-settings');
      await saveUserSettings({ theme: 'dark' });

      expect(mockUpdateUserSettings).toHaveBeenCalledWith({
        body: { theme: 'dark' }
      });
    });

    it('can save editor settings', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });
      const editorSettings = { font_size: 16, tab_size: 2 };

      const { saveUserSettings } = await import('$lib/user-settings');
      await saveUserSettings({ editor: editorSettings });

      expect(mockUpdateUserSettings).toHaveBeenCalledWith({
        body: { editor: editorSettings }
      });
    });

    it('can save multiple settings at once', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('$lib/user-settings');
      await saveUserSettings({ theme: 'dark', editor: { font_size: 18 } });

      expect(mockUpdateUserSettings).toHaveBeenCalledWith({
        body: { theme: 'dark', editor: { font_size: 18 } }
      });
    });

    it('updates store on success', async () => {
      const responseData = { user_id: '123', theme: 'system' };
      mockUpdateUserSettings.mockResolvedValue({ data: responseData, error: null });

      const { saveUserSettings } = await import('$lib/user-settings');
      await saveUserSettings({ theme: 'system' as import('$lib/api').Theme });

      expect(mockSetUserSettings).toHaveBeenCalledWith(responseData);
    });

    it('applies theme locally when theme is saved', async () => {
      const responseData = { user_id: '123', theme: 'dark' };
      mockUpdateUserSettings.mockResolvedValue({ data: responseData, error: null });

      const { saveUserSettings } = await import('$lib/user-settings');
      await saveUserSettings({ theme: 'dark' });

      expect(mockSetTheme).toHaveBeenCalledWith('dark');
    });

    it('applies theme from response even when only editor settings saved', async () => {
      const responseData = { user_id: '123', theme: 'auto', editor: { font_size: 16 } };
      mockUpdateUserSettings.mockResolvedValue({ data: responseData, error: null });

      const { saveUserSettings } = await import('$lib/user-settings');
      await saveUserSettings({ editor: { font_size: 16 } });

      expect(mockSetTheme).toHaveBeenCalledWith('auto');
    });

    it('returns true on success', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: {}, error: null });

      const { saveUserSettings } = await import('$lib/user-settings');
      const result = await saveUserSettings({ theme: 'light' });

      expect(result).toBe(true);
    });

    it('returns false on API error', async () => {
      mockUpdateUserSettings.mockResolvedValue({
        data: null,
        error: { detail: 'Server error' }
      });

      const { saveUserSettings } = await import('$lib/user-settings');
      const result = await saveUserSettings({ theme: 'dark' });

      expect(result).toBe(false);
    });

    it('returns false on network error', async () => {
      mockUpdateUserSettings.mockResolvedValue({ data: undefined, error: new Error('Network error') });

      const { saveUserSettings } = await import('$lib/user-settings');
      const result = await saveUserSettings({ theme: 'dark' });

      expect(result).toBe(false);
    });
  });
});
