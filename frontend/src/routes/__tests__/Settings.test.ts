import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import * as z from 'zod/mini';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeSettingsHistoryEntry, fakeUserSettings } from '#lib/api/@faker-js/faker.gen.ts';
import { queryClient } from '#lib/query-client.ts';
import { toast } from 'svelte-sonner';
import { setMode, userPrefersMode } from 'mode-watcher';
import Settings from '#routes/(auth)/settings/+page.svelte';

function createMockSettings(): UserSettings {
    return {
        ...fakeUserSettings(),
        theme: 'dark',
        notifications: {
            execution_completed: true,
            execution_failed: false,
            system_updates: true,
            security_alerts: false,
        },
        editor: {
            font_size: 16,
            tab_size: 2,
            use_tabs: true,
            word_wrap: false,
            show_line_numbers: true,
        },
    };
}

import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    restoreSettingsApiV1UserSettingsRestorePost,
    getSettingsHistoryApiV1UserSettingsHistoryGet,
    getUserSettingsApiV1UserSettingsGetQueryKey,
    zEditorSettingsInput,
    type UserSettings,
} from '#lib/api/index.ts';

const mocks = vi.hoisted(() => ({
    mockConfirm: vi.fn(),
}));

const historyTable = () => within(screen.getByRole('table', { name: 'Settings history' }));

describe('Settings', () => {
    beforeEach(() => {
        vi.stubGlobal('confirm', mocks.mockConfirm);
        mockApi(getUserSettingsApiV1UserSettingsGet).ok(createMockSettings());
        mockApi(updateUserSettingsApiV1UserSettingsPut).ok(createMockSettings());
    });

    describe('Loading', () => {
        it('calls API on mount and populates form', async () => {
            renderWithQueryClient(Settings);
            await waitFor(() => {
                expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).toHaveBeenCalled();
            });
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
            });
        });
    });

    describe('Tab switching', () => {
        it.each([
            ['General', 'General'],
            ['Editor', 'Editor'],
            ['Notifications', 'Notifications'],
        ])('clicking "%s" tab shows "%s" heading', async (tabName, headingText) => {
            renderWithQueryClient(Settings);
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
            setMode('light');
            mockApi(getUserSettingsApiV1UserSettingsGet).ok({ ...createMockSettings(), theme: 'light' });
            renderWithQueryClient(Settings);
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'General' })).toBeInTheDocument();
            });

            const themeSelect = screen.getByLabelText('Theme');
            expect(themeSelect).toHaveTextContent('light');
            await user.click(themeSelect);
            await user.click(await screen.findByRole('option', { name: 'dark' }));

            expect(userPrefersMode.current).toBe('dark');
            await waitFor(() => expect(themeSelect).toHaveTextContent('dark'));
        });
    });

    describe('Save settings', () => {
        it('shows toast.info when no changes made', async () => {
            renderWithQueryClient(Settings);
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

            renderWithQueryClient(Settings);
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
            expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).toHaveBeenCalledWith(
                expect.objectContaining({
                    body: { theme: null, notifications: null, editor: updatedSettings.editor },
                }),
            );
            await waitFor(() => {
                expect(toast.success).toHaveBeenCalledWith('Settings saved successfully');
            });
            expect(queryClient.getQueryData(getUserSettingsApiV1UserSettingsGetQueryKey())).toEqual(updatedSettings);
        });
        it('counts a value changed back as no change', async () => {
            renderWithQueryClient(Settings);
            await user.click(await screen.findByRole('button', { name: 'Editor' }));
            const fontInput = screen.getByLabelText(/font size/i);
            await user.clear(fontInput);
            await user.type(fontInput, '18');
            await user.clear(fontInput);
            await user.type(fontInput, '16');

            await user.click(screen.getByRole('button', { name: /save settings/i }));
            await waitFor(() => expect(toast.info).toHaveBeenCalledWith('No changes to save'));
            expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).not.toHaveBeenCalled();
        });

        it('takes the font size range from the spec', async () => {
            const { minimum, maximum } = z.toJSONSchema(zEditorSettingsInput.shape.font_size);
            renderWithQueryClient(Settings);
            await user.click(await screen.findByRole('button', { name: 'Editor' }));
            const fontInput = screen.getByLabelText(/font size/i);
            expect(fontInput).toHaveAttribute('min', String(minimum));
            expect(fontInput).toHaveAttribute('max', String(maximum));
        });

        it('opens the tab with the broken rule instead of saving', async () => {
            const { maximum } = z.toJSONSchema(zEditorSettingsInput.shape.font_size);
            renderWithQueryClient(Settings);
            await user.click(await screen.findByRole('button', { name: 'Editor' }));
            const fontInput = screen.getByLabelText(/font size/i);
            await user.clear(fontInput);
            await user.type(fontInput, String(maximum! + 1));
            await user.click(screen.getByRole('button', { name: 'General' }));

            await user.click(screen.getByRole('button', { name: /save settings/i }));
            await waitFor(() =>
                expect(screen.getByLabelText(/font size/i)).toHaveAccessibleDescription(`Must be at most ${maximum}`),
            );
            expect(vi.mocked(updateUserSettingsApiV1UserSettingsPut)).not.toHaveBeenCalled();
        });
    });

    describe('History', () => {
        it('opens history modal and calls API', async () => {
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({
                history: [fakeSettingsHistoryEntry()],
                limit: 10,
            });

            renderWithQueryClient(Settings);
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

            renderWithQueryClient(Settings);
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
        it('restores settings on confirm', async () => {
            mocks.mockConfirm.mockReturnValue(true);
            mockApi(restoreSettingsApiV1UserSettingsRestorePost).ok({ ...createMockSettings(), theme: 'light' });
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({
                history: [{ ...fakeSettingsHistoryEntry(), timestamp: '2025-01-15T10:00:00Z' }],
                limit: 10,
            });

            renderWithQueryClient(Settings);
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
            mockApi(getSettingsHistoryApiV1UserSettingsHistoryGet).ok({
                history: [{ ...fakeSettingsHistoryEntry(), timestamp: '2025-01-15T10:00:00Z' }],
                limit: 10,
            });

            renderWithQueryClient(Settings);
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
