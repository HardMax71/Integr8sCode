import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import * as z from 'zod/mini';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import { fieldTitle } from '#lib/formatters.ts';
import { queryClient } from '#lib/query-client.ts';
import AdminSettings from '#routes/admin/settings/+page.svelte';

import {
    getSystemSettingsApiV1AdminSettingsGet,
    updateSystemSettingsApiV1AdminSettingsPut,
    resetSystemSettingsApiV1AdminSettingsResetPost,
    zSystemSettingsSchemaInput,
    zSystemSettingsSchemaOutput,
} from '#lib/api/index.ts';

// The spec's defaults, with a few values changed so the form shows something to check
function createMockSystemSettings() {
    return zSystemSettingsSchemaOutput.parse({
        max_timeout_seconds: 60,
        session_timeout_minutes: 30,
        sampling_rate: 0.5,
    });
}

const mocks = vi.hoisted(() => ({
    mockConfirm: vi.fn(),
}));

describe('AdminSettings', () => {
    beforeEach(() => {
        vi.stubGlobal('confirm', mocks.mockConfirm);
        mockApi(getSystemSettingsApiV1AdminSettingsGet).ok(createMockSystemSettings());
        mockApi(updateSystemSettingsApiV1AdminSettingsPut).ok(createMockSystemSettings());
        mockApi(resetSystemSettingsApiV1AdminSettingsResetPost).ok(createMockSystemSettings());
    });

    function renderAdminSettings() {
        return renderWithQueryClient(AdminSettings);
    }

    describe('Loading', () => {
        it('calls API on mount and shows page heading', async () => {
            await renderAdminSettings();
            await waitFor(() => {
                expect(vi.mocked(getSystemSettingsApiV1AdminSettingsGet)).toHaveBeenCalledOnce();
            });
            expect(screen.getByRole('heading', { name: 'System Settings' })).toBeInTheDocument();
        });
    });

    describe('Form population', () => {
        it.each(Object.entries(createMockSystemSettings()))('field %s is populated with %s', async (key, value) => {
            await renderAdminSettings();
            await waitFor(() => {
                const input = screen.getByLabelText(fieldTitle(key)) as HTMLInputElement | HTMLSelectElement;
                expect(input.value).toBe(String(value));
            });
        });

        it('takes min and max for a number from the spec', async () => {
            const { minimum, maximum } = z.toJSONSchema(zSystemSettingsSchemaInput.shape.max_login_attempts);
            await renderAdminSettings();
            const input = await screen.findByLabelText('Max Login Attempts');
            expect(input).toHaveAttribute('min', String(minimum));
            expect(input).toHaveAttribute('max', String(maximum));
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
                expect(vi.mocked(updateSystemSettingsApiV1AdminSettingsPut)).toHaveBeenCalled();
            });
            expect(vi.mocked(updateSystemSettingsApiV1AdminSettingsPut)).toHaveBeenCalledWith(
                expect.objectContaining({ body: createMockSystemSettings() }),
            );
            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Settings saved successfully'));
        });

        it('shows the broken rule under the field and does not save', async () => {
            const { maximum } = z.toJSONSchema(zSystemSettingsSchemaInput.shape.max_login_attempts);
            await renderAdminSettings();
            const input = await screen.findByLabelText('Max Login Attempts');
            await user.clear(input);
            await user.type(input, String(maximum! + 1));
            await user.click(screen.getByRole('button', { name: /save settings/i }));

            await waitFor(() => expect(input).toHaveAccessibleDescription(`Must be at most ${maximum}`));
            expect(vi.mocked(updateSystemSettingsApiV1AdminSettingsPut)).not.toHaveBeenCalled();
        });

        it('handles save error without crashing', async () => {
            mockApi(updateSystemSettingsApiV1AdminSettingsPut).err({ status: 500, detail: 'Save failed' });
            await renderAdminSettings();
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /save settings/i })).toBeInTheDocument();
            });
            await user.click(screen.getByRole('button', { name: /save settings/i }));
            await waitFor(() => expect(queryClient.getMutationCache().getAll()[0]?.state.status).toBe('error'));
            expect(vi.mocked(updateSystemSettingsApiV1AdminSettingsPut)).toHaveBeenCalled();
            expect(toast.success).not.toHaveBeenCalled();
        });
    });

    describe('Reset', () => {
        it('calls confirm, resets on true, updates form, shows toast', async () => {
            mocks.mockConfirm.mockReturnValue(true);
            const resetData = zSystemSettingsSchemaOutput.parse({
                max_timeout_seconds: 30,
                memory_limit: '256Mi',
                cpu_limit: '1000m',
                max_concurrent_executions: 5,
                max_executions_per_user: 50,
                password_min_length: 10,
                max_login_attempts: 3,
                lockout_duration_minutes: 10,
                metrics_retention_days: 7,
                log_level: 'WARNING',
                enable_tracing: false,
                sampling_rate: 1.0,
            });
            mockApi(resetSystemSettingsApiV1AdminSettingsResetPost).ok(resetData);

            await renderAdminSettings();
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeInTheDocument();
            });

            await user.click(screen.getByRole('button', { name: /reset to defaults/i }));
            expect(mocks.mockConfirm).toHaveBeenCalled();
            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Settings reset to defaults'));
            expect(vi.mocked(resetSystemSettingsApiV1AdminSettingsResetPost)).toHaveBeenCalled();
            await waitFor(() => expect(screen.getByLabelText('Max Executions Per User')).toHaveValue(50));
            expect(screen.getByLabelText('Max Timeout Seconds')).toHaveValue(30);
        });

        it('does not call API when confirm returns false', async () => {
            mocks.mockConfirm.mockReturnValue(false);
            await renderAdminSettings();
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeInTheDocument();
            });

            await user.click(screen.getByRole('button', { name: /reset to defaults/i }));
            expect(vi.mocked(resetSystemSettingsApiV1AdminSettingsResetPost)).not.toHaveBeenCalled();
        });
    });

    describe('Button states', () => {
        it('disables both buttons while saving', async () => {
            let resolveSave: (v: unknown) => void;
            mockApi(updateSystemSettingsApiV1AdminSettingsPut).mock.mockImplementation(
                () =>
                    new Promise((r) => {
                        resolveSave = r;
                    }),
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
            mockApi(resetSystemSettingsApiV1AdminSettingsResetPost).mock.mockImplementation(
                () =>
                    new Promise((r) => {
                        resolveReset = r;
                    }),
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
