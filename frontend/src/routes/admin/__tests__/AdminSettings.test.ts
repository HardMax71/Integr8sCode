import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

function createMockSystemSettings() {
  return {
    max_timeout_seconds: 60,
    memory_limit: '512Mi',
    cpu_limit: '2000m',
    max_concurrent_executions: 10,
    password_min_length: 8,
    session_timeout_minutes: 30,
    max_login_attempts: 5,
    lockout_duration_minutes: 15,
    metrics_retention_days: 30,
    log_level: 'INFO',
    enable_tracing: true,
    sampling_rate: 0.5,
  };
}

const mocks = vi.hoisted(() => ({
  getSystemSettingsApiV1AdminSettingsGet: vi.fn(),
  updateSystemSettingsApiV1AdminSettingsPut: vi.fn(),
  resetSystemSettingsApiV1AdminSettingsResetPost: vi.fn(),
  addToast: vi.fn(),
  mockConfirm: vi.fn(),
  mockAuthStore: {
    isAuthenticated: true,
    username: 'adminuser',
    userRole: 'admin',
    verifyAuth: vi.fn(),
  },
}));

vi.mock('../../../lib/api', () => ({
  getSystemSettingsApiV1AdminSettingsGet: (...args: unknown[]) => mocks.getSystemSettingsApiV1AdminSettingsGet(...args),
  updateSystemSettingsApiV1AdminSettingsPut: (...args: unknown[]) => mocks.updateSystemSettingsApiV1AdminSettingsPut(...args),
  resetSystemSettingsApiV1AdminSettingsResetPost: (...args: unknown[]) => mocks.resetSystemSettingsApiV1AdminSettingsResetPost(...args),
}));

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));

vi.mock('@mateothegreat/svelte5-router', async () =>
  (await import('$test/test-utils')).createMockRouterModule());

vi.mock('svelte-sonner', async () =>
  (await import('$test/test-utils')).createToastMock(mocks.addToast));

vi.mock('$routes/admin/AdminLayout.svelte', () =>
  import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte'));

vi.mock('$components/Spinner.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<span>Loading</span>', 'spinner'));

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('ShieldCheck'));

describe('AdminSettings', () => {
  const user = userEvent.setup();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('confirm', mocks.mockConfirm);
    mocks.getSystemSettingsApiV1AdminSettingsGet.mockResolvedValue({
      data: createMockSystemSettings(),
      error: undefined,
    });
    mocks.updateSystemSettingsApiV1AdminSettingsPut.mockResolvedValue({
      data: createMockSystemSettings(),
      error: undefined,
    });
    mocks.resetSystemSettingsApiV1AdminSettingsResetPost.mockResolvedValue({
      data: createMockSystemSettings(),
      error: undefined,
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  async function renderAdminSettings() {
    const { default: AdminSettings } = await import('$routes/admin/AdminSettings.svelte');
    return render(AdminSettings);
  }

  describe('Loading', () => {
    it('calls API on mount and shows page heading', async () => {
      await renderAdminSettings();
      await waitFor(() => {
        expect(mocks.getSystemSettingsApiV1AdminSettingsGet).toHaveBeenCalledOnce();
      });
      expect(screen.getByRole('heading', { name: 'System Settings' })).toBeInTheDocument();
    });
  });

  describe('Form population', () => {
    it.each([
      ['Max Timeout (seconds)', '60'],
      ['Memory Limit (e.g. 512Mi)', '512Mi'],
      ['CPU Limit (e.g. 2000m)', '2000m'],
      ['Max Concurrent Executions', '10'],
      ['Min Password Length', '8'],
      ['Session Timeout (minutes)', '30'],
      ['Max Login Attempts', '5'],
      ['Lockout Duration (minutes)', '15'],
      ['Metrics Retention Days', '30'],
      ['Sampling Rate', '0.5'],
    ])('field "%s" is populated with "%s"', async (label, expectedValue) => {
      await renderAdminSettings();
      await waitFor(() => {
        const input = screen.getByLabelText(label) as HTMLInputElement;
        expect(input.value).toBe(expectedValue);
      });
    });

    it('log-level select has value "INFO"', async () => {
      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByLabelText('Log Level')).toHaveValue('INFO');
      });
    });
  });

  describe('Save', () => {
    it('calls update API with current settings and shows success toast', async () => {
      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /save settings/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /save settings/i }));
      await waitFor(() => {
        expect(mocks.updateSystemSettingsApiV1AdminSettingsPut).toHaveBeenCalled();
      });
      const callArgs = mocks.updateSystemSettingsApiV1AdminSettingsPut.mock.calls[0]![0];
      expect(callArgs.body).toHaveProperty('max_timeout_seconds');
      expect(callArgs.body).toHaveProperty('password_min_length');
      expect(callArgs.body).toHaveProperty('metrics_retention_days');
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Settings saved successfully');
    });

    it('handles save error without crashing', async () => {
      mocks.updateSystemSettingsApiV1AdminSettingsPut.mockResolvedValue({
        data: undefined,
        error: { detail: 'Save failed' },
      });
      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /save settings/i })).toBeInTheDocument();
      });
      await user.click(screen.getByRole('button', { name: /save settings/i }));
      await waitFor(() => {
        expect(mocks.updateSystemSettingsApiV1AdminSettingsPut).toHaveBeenCalled();
      });
      expect(mocks.addToast).not.toHaveBeenCalledWith('success', expect.anything());
    });
  });

  describe('Reset', () => {
    it('calls confirm, resets on true, updates form, shows toast', async () => {
      mocks.mockConfirm.mockReturnValue(true);
      const resetData = {
        max_timeout_seconds: 30,
        memory_limit: '256Mi',
        cpu_limit: '1000m',
        max_concurrent_executions: 5,
        password_min_length: 6,
        session_timeout_minutes: 60,
        max_login_attempts: 3,
        lockout_duration_minutes: 10,
        metrics_retention_days: 7,
        log_level: 'WARNING',
        enable_tracing: false,
        sampling_rate: 1.0,
      };
      mocks.resetSystemSettingsApiV1AdminSettingsResetPost.mockResolvedValue({
        data: resetData,
        error: undefined,
      });

      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /reset to defaults/i }));
      expect(mocks.mockConfirm).toHaveBeenCalled();
      await waitFor(() => {
        expect(mocks.resetSystemSettingsApiV1AdminSettingsResetPost).toHaveBeenCalled();
      });
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Settings reset to defaults');

      await waitFor(() => {
        const timeoutInput = document.getElementById('max-timeout') as HTMLInputElement;
        expect(timeoutInput.value).toBe('30');
      });
    });

    it('does not call API when confirm returns false', async () => {
      mocks.mockConfirm.mockReturnValue(false);
      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /reset to defaults/i }));
      expect(mocks.resetSystemSettingsApiV1AdminSettingsResetPost).not.toHaveBeenCalled();
    });
  });

  describe('Button states', () => {
    it('disables both buttons while saving', async () => {
      let resolveSave: (v: unknown) => void;
      mocks.updateSystemSettingsApiV1AdminSettingsPut.mockImplementation(
        () => new Promise((r) => { resolveSave = r; })
      );

      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /save settings/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /save settings/i }));
      await waitFor(() => {
        expect(screen.getByText('Saving...')).toBeInTheDocument();
      });
      expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeDisabled();

      resolveSave!({ data: createMockSystemSettings(), error: undefined });
      await waitFor(() => {
        expect(screen.queryByText('Saving...')).not.toBeInTheDocument();
      });
    });

    it('shows "Resetting..." text while resetting', async () => {
      mocks.mockConfirm.mockReturnValue(true);
      let resolveReset: (v: unknown) => void;
      mocks.resetSystemSettingsApiV1AdminSettingsResetPost.mockImplementation(
        () => new Promise((r) => { resolveReset = r; })
      );

      await renderAdminSettings();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /reset to defaults/i }));
      await waitFor(() => {
        expect(screen.getByText('Resetting...')).toBeInTheDocument();
      });

      resolveReset!({ data: createMockSystemSettings(), error: undefined });
      await waitFor(() => {
        expect(screen.queryByText('Resetting...')).not.toBeInTheDocument();
      });
    });
  });
});
