import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { userSettings, editorSettings, setUserSettings, clearUserSettings } from '$stores/userSettings';
import type { UserSettings } from '$lib/api';

const DEFAULTS = {
    theme: 'auto',
    font_size: 14,
    tab_size: 4,
    use_tabs: false,
    word_wrap: true,
    show_line_numbers: true,
};

describe('userSettings store', () => {
    beforeEach(() => clearUserSettings());

    it('starts as null', () => {
        expect(get(userSettings)).toBeNull();
    });

    it.each([
        ['object', { editor: { font_size: 16 } } as UserSettings],
        ['null', null],
    ])('setUserSettings accepts %s', (_, value) => {
        setUserSettings(value);
        expect(get(userSettings)).toEqual(value);
    });

    it('clearUserSettings resets to null', () => {
        setUserSettings({ editor: { font_size: 20 } } as UserSettings);
        clearUserSettings();
        expect(get(userSettings)).toBeNull();
    });

    describe('editorSettings (derived)', () => {
        it('returns defaults when userSettings is null', () => {
            expect(get(editorSettings)).toEqual(DEFAULTS);
        });

        it.each([
            ['partial override', { font_size: 20, tab_size: 2 }, { ...DEFAULTS, font_size: 20, tab_size: 2 }],
            ['full override', { theme: 'dark', font_size: 18, tab_size: 8, use_tabs: true, word_wrap: false, show_line_numbers: false },
                { theme: 'dark', font_size: 18, tab_size: 8, use_tabs: true, word_wrap: false, show_line_numbers: false }],
        ])('merges %s with defaults', (_, editor, expected) => {
            setUserSettings({ editor } as UserSettings);
            expect(get(editorSettings)).toEqual(expected);
        });

        it('reverts to defaults when cleared', () => {
            setUserSettings({ editor: { font_size: 20 } } as UserSettings);
            clearUserSettings();
            expect(get(editorSettings)).toEqual(DEFAULTS);
        });
    });
});
