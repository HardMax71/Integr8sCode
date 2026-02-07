import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock } from '$lib/../__tests__/test-utils';

function createMockSettings() {
  return {
    theme: 'dark',
    notifications: {
      execution_completed: true,
      execution_failed: false,
      system_updates: true,
      security_alerts: false,
      channels: ['in_app'],
    },
    editor: {
      theme: 'one-dark',
      font_size: 16,
      tab_size: 2,
      use_tabs: true,
      word_wrap: false,
      show_line_numbers: true,
    },
  };
}

const mocks = vi.hoisted(() => ({
  getUserSettingsApiV1UserSettingsGet: vi.fn(),
  updateUserSettingsApiV1UserSettingsPut: vi.fn(),
  restoreSettingsApiV1UserSettingsRestorePost: vi.fn(),
  getSettingsHistoryApiV1UserSettingsHistoryGet: vi.fn(),
  addToast: vi.fn(),
  mockSetTheme: vi.fn(),
  mockSetUserSettings: vi.fn(),
  mockConfirm: vi.fn(),
  mockAuthStore: {
    isAuthenticated: true,
    username: 'testuser',
    userRole: 'user',
    verifyAuth: vi.fn(),
  },
}));

vi.mock('$lib/api', () => ({
  getUserSettingsApiV1UserSettingsGet: (...args: unknown[]) => mocks.getUserSettingsApiV1UserSettingsGet(...args),
  updateUserSettingsApiV1UserSettingsPut: (...args: unknown[]) => mocks.updateUserSettingsApiV1UserSettingsPut(...args),
  restoreSettingsApiV1UserSettingsRestorePost: (...args: unknown[]) => mocks.restoreSettingsApiV1UserSettingsRestorePost(...args),
  getSettingsHistoryApiV1UserSettingsHistoryGet: (...args: unknown[]) => mocks.getSettingsHistoryApiV1UserSettingsHistoryGet(...args),
}));

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));
vi.mock('$stores/theme.svelte', () => ({ setTheme: (...args: unknown[]) => mocks.mockSetTheme(...args) }));
vi.mock('$stores/userSettings.svelte', () => ({
  setUserSettings: (...args: unknown[]) => mocks.mockSetUserSettings(...args),
  userSettingsStore: { settings: null, editorSettings: {} },
}));

vi.mock('svelte-sonner', async () =>
  (await import('$lib/../__tests__/test-utils')).createToastMock(mocks.addToast));

vi.mock('$components/Spinner.svelte', async () =>
  (await import('$lib/../__tests__/test-utils')).createMockSvelteComponent('<span>Loading</span>', 'spinner'));

vi.mock('@lucide/svelte', async () =>
  (await import('$lib/../__tests__/test-utils')).createMockIconModule('ChevronDown'));

describe('Settings', () => {
  const user = userEvent.setup();

  beforeEach(() => {
    vi.clearAllMocks();
    setupAnimationMock();
    vi.stubGlobal('confirm', mocks.mockConfirm);
    mocks.mockAuthStore.isAuthenticated = true;
    mocks.getUserSettingsApiV1UserSettingsGet.mockResolvedValue({
      data: createMockSettings(),
      error: undefined,
    });
    mocks.updateUserSettingsApiV1UserSettingsPut.mockResolvedValue({
      data: createMockSettings(),
      error: undefined,
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  async function renderSettings() {
    const { default: Settings } = await import('$routes/Settings.svelte');
    return render(Settings);
  }

  describe('Loading', () => {
    it('calls API on mount and populates form', async () => {
      await renderSettings();
      await waitFor(() => {
        expect(mocks.getUserSettingsApiV1UserSettingsGet).toHaveBeenCalled();
      });
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });
    });

    it('does not call API when unauthenticated', async () => {
      mocks.mockAuthStore.isAuthenticated = false;
      await renderSettings();
      expect(mocks.getUserSettingsApiV1UserSettingsGet).not.toHaveBeenCalled();
    });
  });

  describe('Tab switching', () => {
    it.each([
      ['General', 'General Settings'],
      ['Editor', 'Editor Settings'],
      ['Notifications', 'Notification Settings'],
    ])('clicking "%s" tab shows "%s" heading', async (tabName, headingText) => {
      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });
      await user.click(screen.getByRole('button', { name: tabName }));
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: headingText })).toBeInTheDocument();
      });
    });
  });

  describe('Theme dropdown', () => {
    it('selects "Dark" and calls setTheme with "dark"', async () => {
      mocks.getUserSettingsApiV1UserSettingsGet.mockResolvedValue({
        data: { ...createMockSettings(), theme: 'light' },
        error: undefined,
      });
      await renderSettings();
      await waitFor(() => {
        expect(screen.getByText('General Settings')).toBeInTheDocument();
      });

      const themeButton = document.getElementById('theme-select') as HTMLButtonElement;
      expect(themeButton).toBeTruthy();
      await user.click(themeButton);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Dark' })).toBeInTheDocument();
      });
      await user.click(screen.getByRole('button', { name: 'Dark' }));
      expect(mocks.mockSetTheme).toHaveBeenCalledWith('dark');
    });
  });

  describe('Save settings', () => {
    it('shows toast.info when no changes made', async () => {
      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });
      await user.click(screen.getByRole('button', { name: /save settings/i }));
      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('info', 'No changes to save');
      });
      expect(mocks.updateUserSettingsApiV1UserSettingsPut).not.toHaveBeenCalled();
    });

    it('saves changed editor settings and shows success toast', async () => {
      const settings = createMockSettings();
      const updatedSettings = { ...settings, editor: { ...settings.editor, font_size: 18 } };
      mocks.updateUserSettingsApiV1UserSettingsPut.mockResolvedValue({
        data: updatedSettings,
        error: undefined,
      });

      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Editor' }));
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Editor Settings' })).toBeInTheDocument();
      });

      const fontInput = screen.getByLabelText(/font size/i);
      await user.clear(fontInput);
      await user.type(fontInput, '18');

      await user.click(screen.getByRole('button', { name: /save settings/i }));
      await waitFor(() => {
        expect(mocks.updateUserSettingsApiV1UserSettingsPut).toHaveBeenCalled();
      });
      const callArgs = mocks.updateUserSettingsApiV1UserSettingsPut.mock.calls[0][0];
      expect(callArgs.body).toHaveProperty('editor');
      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('success', 'Settings saved successfully');
      });
      expect(mocks.mockSetUserSettings).toHaveBeenCalled();
    });
  });

  describe('History', () => {
    it('opens history modal and calls API', async () => {
      mocks.getSettingsHistoryApiV1UserSettingsHistoryGet.mockResolvedValue({
        data: {
          history: [
            { timestamp: '2025-01-15T10:00:00Z', field: 'theme', old_value: 'light', new_value: 'dark' },
          ],
        },
        error: undefined,
      });

      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /view history/i }));
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings History' })).toBeInTheDocument();
      });
      expect(mocks.getSettingsHistoryApiV1UserSettingsHistoryGet).toHaveBeenCalledWith({
        query: { limit: 10 },
      });
    });

    it('uses cache on second open within 30s', async () => {
      mocks.getSettingsHistoryApiV1UserSettingsHistoryGet.mockResolvedValue({
        data: { history: [] },
        error: undefined,
      });

      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /view history/i }));
      await waitFor(() => {
        expect(mocks.getSettingsHistoryApiV1UserSettingsHistoryGet).toHaveBeenCalledTimes(1);
      });

      await user.click(screen.getByRole('button', { name: 'Close' }));
      await user.click(screen.getByRole('button', { name: /view history/i }));
      expect(mocks.getSettingsHistoryApiV1UserSettingsHistoryGet).toHaveBeenCalledTimes(1);
    });
  });

  describe('Restore', () => {
    const historyEntry = { timestamp: '2025-01-15T10:00:00Z', field: 'theme', old_value: 'light', new_value: 'dark' };

    function setupHistoryMock() {
      mocks.getSettingsHistoryApiV1UserSettingsHistoryGet.mockResolvedValue({
        data: { history: [historyEntry] },
        error: undefined,
      });
    }

    it('restores settings on confirm', async () => {
      mocks.mockConfirm.mockReturnValue(true);
      mocks.restoreSettingsApiV1UserSettingsRestorePost.mockResolvedValue({
        data: { ...createMockSettings(), theme: 'light' },
        error: undefined,
      });
      setupHistoryMock();

      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /view history/i }));
      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Restore' }));
      await waitFor(() => {
        expect(mocks.restoreSettingsApiV1UserSettingsRestorePost).toHaveBeenCalledWith({
          body: { timestamp: '2025-01-15T10:00:00Z', reason: 'User requested restore' },
        });
      });
      expect(mocks.mockSetTheme).toHaveBeenCalledWith('light');
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Settings restored successfully');
    });

    it('does not call API when confirm is cancelled', async () => {
      mocks.mockConfirm.mockReturnValue(false);
      setupHistoryMock();

      await renderSettings();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /view history/i }));
      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Restore' }));
      expect(mocks.restoreSettingsApiV1UserSettingsRestorePost).not.toHaveBeenCalled();
    });
  });
});
