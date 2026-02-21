import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { UserSettings } from '$lib/api';

const DEFAULTS = {
    font_size: 14,
    tab_size: 4,
    use_tabs: false,
    word_wrap: true,
    show_line_numbers: true,
};

describe('userSettings store', () => {
    beforeEach(async () => {
        vi.resetModules();
    });

    it('starts as null', async () => {
        const { userSettingsStore } = await import('$stores/userSettings.svelte');
        expect(userSettingsStore.settings).toBeNull();
    });

    it.each([
        ['object', { editor: { font_size: 16 } } as UserSettings],
        ['null', null],
    ])('setUserSettings accepts %s', async (_, value) => {
        const { userSettingsStore, setUserSettings } = await import('$stores/userSettings.svelte');
        setUserSettings(value);
        expect(userSettingsStore.settings).toEqual(value);
    });

    it('clearUserSettings resets to null', async () => {
        const { userSettingsStore, setUserSettings, clearUserSettings } = await import('$stores/userSettings.svelte');
        setUserSettings({ editor: { font_size: 20 } } as UserSettings);
        clearUserSettings();
        expect(userSettingsStore.settings).toBeNull();
    });

    describe('editorSettings (derived)', () => {
        it('returns defaults when userSettings is null', async () => {
            const { userSettingsStore } = await import('$stores/userSettings.svelte');
            expect(userSettingsStore.editorSettings).toEqual(DEFAULTS);
        });

        it.each([
            ['complete settings', { font_size: 20, tab_size: 2, use_tabs: false, word_wrap: true, show_line_numbers: true },
                { font_size: 20, tab_size: 2, use_tabs: false, word_wrap: true, show_line_numbers: true }],
            ['full override', { font_size: 18, tab_size: 8, use_tabs: true, word_wrap: false, show_line_numbers: false },
                { font_size: 18, tab_size: 8, use_tabs: true, word_wrap: false, show_line_numbers: false }],
        ])('returns %s from API', async (_, editor, expected) => {
            const { userSettingsStore, setUserSettings } = await import('$stores/userSettings.svelte');
            setUserSettings({ editor } as UserSettings);
            expect(userSettingsStore.editorSettings).toEqual(expected);
        });

        it('reverts to defaults when cleared', async () => {
            const { userSettingsStore, setUserSettings, clearUserSettings } = await import('$stores/userSettings.svelte');
            setUserSettings({ editor: { font_size: 20 } } as UserSettings);
            clearUserSettings();
            expect(userSettingsStore.editorSettings).toEqual(DEFAULTS);
        });
    });
});
