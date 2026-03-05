import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user, mockApi } from '$test/test-utils';
import { toast } from 'svelte-sonner';
import Settings from '$routes/Settings.svelte';

function createMockSettings() {
    return {
        user_id: 'user-1',
        theme: 'dark',
        timezone: 'UTC',
        date_format: 'YYYY-MM-DD',
        time_format: '24h',
        notifications: {
            execution_completed: true,
            execution_failed: false,
            system_updates: true,
            security_alerts: false,
            channels: ['in_app'],
        },
        editor: {
            font_size: 16,
            tab_size: 2,
            use_tabs: true,
            word_wrap: false,
            show_line_numbers: true,
        },
        custom_settings: {},
        version: 1,
    };
}

import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    restoreSettingsApiV1UserSettingsRestorePost,
    getSettingsHistoryApiV1UserSettingsHistoryGet,
} from '$lib/api';

const mocks = vi.hoisted(() => ({
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

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));
vi.mock('$stores/theme.svelte', () => ({ setTheme: (...args: unknown[]) => mocks.mockSetTheme(...args) }));
vi.mock('$stores/userSettings.svelte', () => ({
    setUserSettings: (...args: unknown[]) => mocks.mockSetUserSettings(...args),
    userSettingsStore: { settings: null, editorSettings: {} },
}));

describe('Settings', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal('confirm', mocks.mockConfirm);
        mocks.mockAuthStore.isAuthenticated = true;
        mockApi(getUserSettingsApiV1UserSettingsGet).ok(createMockSettings());
        mockApi(updateUserSettingsApiV1UserSettingsPut).ok(createMockSettings());
    });

    afterEach(() => vi.unstubAllGlobals());

    function renderSettings() {
        return render(Settings);
    }

    describe('Loading', () => {
        it('calls API on mount and populates form', async () => {
            await renderSettings();
            await waitFor(() => {
                expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).toHaveBeenCalled();
            });
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
            });
        });

        it('does not call API when unauthenticated', async () => {
            mocks.mockAuthStore.isAuthenticated = false;
            await renderSettings();
            expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).not.toHaveBeenCalled();
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
            mockApi(getUserSettingsApiV1UserSettingsGet).ok({ ...createMockSettings(), theme: 'light' });
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
                expect(toast.info).toHaveBeenCalledWith('No changes to save');
            });
            expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).not.toHaveBeenCalled();
        });

        it('saves changed editor settings and shows success toast', async () => {
            const settings = createMockSettings();
            const updatedSettings = { ...settings, editor: { ...settings.editor, font_size: 18 } };
            mockApi(updateUserSettingsApiV1UserSettingsPut).ok(updatedSettings);

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
                expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).toHaveBeenCalled();
            });
            const callArgs = vi.mocked(updateUserSettingsApiV1UserSettingsPut).mock.calls[0]![0];
            expect(callArgs.body).toHaveProperty('editor');
            await waitFor(() => {
                expect(toast.success).toHaveBeenCalledWith('Settings saved successfully');
            });
            expect(mocks.mockSetUserSettings).toHaveBeenCalled();
        });
    });

    describe('History', () => {
        it('opens history modal and calls API', async () => {
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({
                history: [
                    {
                        timestamp: '2025-01-15T10:00:00Z',
                        event_type: 'settings_updated',
                        field: 'theme',
                        old_value: 'light',
                        new_value: 'dark',
                        reason: null,
                    },
                ],
                limit: 10,
            });

            await renderSettings();
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
            });

            await user.click(screen.getByRole('button', { name: /view history/i }));
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Settings History' })).toBeInTheDocument();
            });
            expect(vi.mocked(getSettingsHistoryApiV1UserSettingsHistoryGet)).toHaveBeenCalledWith({
                query: { limit: 10 },
            });
        });

        it('uses cache on second open within 30s', async () => {
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({ history: [], limit: 10 });

            await renderSettings();
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
            });

            await user.click(screen.getByRole('button', { name: /view history/i }));
            await waitFor(() => {
                expect(vi.mocked(getSettingsHistoryApiV1UserSettingsHistoryGet)).toHaveBeenCalledTimes(1);
            });

            await user.click(screen.getByRole('button', { name: 'Close' }));
            await user.click(screen.getByRole('button', { name: /view history/i }));
            expect(vi.mocked(getSettingsHistoryApiV1UserSettingsHistoryGet)).toHaveBeenCalledTimes(1);
        });
    });

    describe('Restore', () => {
        const historyEntry = {
            timestamp: '2025-01-15T10:00:00Z',
            event_type: 'settings_updated' as const,
            field: 'theme',
            old_value: 'light',
            new_value: 'dark',
            reason: null,
        };

        function setupHistoryMock() {
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({ history: [historyEntry], limit: 10 });
        }

        it('restores settings on confirm', async () => {
            mocks.mockConfirm.mockReturnValue(true);
            mockApi(restoreSettingsApiV1UserSettingsRestorePost).ok({ ...createMockSettings(), theme: 'light' });
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
                expect(vi.mocked(restoreSettingsApiV1UserSettingsRestorePost)).toHaveBeenCalledWith({
                    body: { timestamp: '2025-01-15T10:00:00Z', reason: 'User requested restore' },
                });
            });
            expect(mocks.mockSetTheme).toHaveBeenCalledWith('light');
            expect(toast.success).toHaveBeenCalledWith('Settings restored successfully');
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
            expect(vi.mocked(restoreSettingsApiV1UserSettingsRestorePost)).not.toHaveBeenCalled();
        });
    });
});
