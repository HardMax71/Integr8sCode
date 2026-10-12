import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import { user, mockApi, renderWithQueryClient, createMockUserSettings } from '#test/test-utils.ts';
import { queryClient } from '#lib/query-client.ts';
import { toast } from 'svelte-sonner';
import Settings from '#routes/(auth)/settings/+page.svelte';

function createMockSettings() {
    return createMockUserSettings({
        theme: 'dark',
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
    });
}

import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    restoreSettingsApiV1UserSettingsRestorePost,
    getSettingsHistoryApiV1UserSettingsHistoryGet,
    getUserSettingsApiV1UserSettingsGetQueryKey,
    type SettingsHistoryEntry,
} from '#lib/api/index.ts';

const mocks = vi.hoisted(() => ({
    mockSetTheme: vi.fn(),
    mockConfirm: vi.fn(),
    mockAuthStore: {
        isAuthenticated: true,
    },
}));

vi.mock('#stores/auth.svelte.ts', () => ({ authStore: mocks.mockAuthStore }));
vi.mock('#stores/theme.svelte.ts', () => ({ setTheme: (...args: unknown[]) => mocks.mockSetTheme(...args) }));

const historyTable = () => within(screen.getByRole('table', { name: 'Settings history' }));

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
        return renderWithQueryClient(Settings);
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
            ['General', 'General'],
            ['Editor', 'Editor'],
            ['Notifications', 'Notifications'],
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
        it('picks "dark" from the theme list, previews it and shows it as the choice', async () => {
            mockApi(getUserSettingsApiV1UserSettingsGet).ok({ ...createMockSettings(), theme: 'light' });
            await renderSettings();
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'General' })).toBeInTheDocument();
            });

            const themeSelect = screen.getByLabelText('Theme');
            expect(themeSelect).toHaveTextContent('light');
            await user.click(themeSelect);
            await user.click(await screen.findByRole('option', { name: 'dark' }));

            expect(mocks.mockSetTheme).toHaveBeenCalledWith('dark');
            await waitFor(() => expect(themeSelect).toHaveTextContent('dark'));
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
                expect(screen.getByRole('heading', { name: 'Editor' })).toBeInTheDocument();
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
            expect(queryClient.getQueryData(getUserSettingsApiV1UserSettingsGetQueryKey())).toEqual(updatedSettings);
        });
    });

    describe('History', () => {
        it('opens history modal and calls API', async () => {
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({
                history: [
                    {
                        timestamp: '2025-01-15T10:00:00Z',
                        event_type: 'user_settings_updated',
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
            expect(vi.mocked(getSettingsHistoryApiV1UserSettingsHistoryGet)).toHaveBeenCalledWith(
                expect.objectContaining({ query: { limit: 10 } }),
            );
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

            await user.keyboard('{Escape}');
            await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
            await user.click(screen.getByRole('button', { name: /view history/i }));
            await screen.findByRole('dialog', { name: 'Settings History' });
            expect(vi.mocked(getSettingsHistoryApiV1UserSettingsHistoryGet)).toHaveBeenCalledTimes(1);
        });
    });

    describe('Restore', () => {
        const historyEntry: SettingsHistoryEntry = {
            timestamp: '2025-01-15T10:00:00Z',
            event_type: 'user_settings_updated',
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
                expect(historyTable().getByRole('button', { name: 'Restore' })).toBeInTheDocument();
            });

            await user.click(historyTable().getByRole('button', { name: 'Restore' }));
            await waitFor(() => {
                expect(toast.success).toHaveBeenCalledWith('Settings restored successfully');
            });
            expect(vi.mocked(restoreSettingsApiV1UserSettingsRestorePost)).toHaveBeenCalledWith(
                expect.objectContaining({
                    body: { timestamp: '2025-01-15T10:00:00Z' },
                }),
            );
            expect(queryClient.getQueryData(getUserSettingsApiV1UserSettingsGetQueryKey())).toMatchObject({
                theme: 'light',
            });
            await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
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
                expect(historyTable().getByRole('button', { name: 'Restore' })).toBeInTheDocument();
            });

            await user.click(historyTable().getByRole('button', { name: 'Restore' }));
            expect(vi.mocked(restoreSettingsApiV1UserSettingsRestorePost)).not.toHaveBeenCalled();
        });
    });
});
