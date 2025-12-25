import { writable, derived, get } from 'svelte/store';
import type { UserSettings, EditorSettings } from '../lib/api';

const DEFAULT_EDITOR_SETTINGS: EditorSettings = {
    theme: 'auto',
    font_size: 14,
    tab_size: 4,
    use_tabs: false,
    word_wrap: true,
    show_line_numbers: true,
};

export const userSettings = writable<UserSettings | null>(null);

export const editorSettings = derived(userSettings, ($userSettings) => ({
    ...DEFAULT_EDITOR_SETTINGS,
    ...$userSettings?.editor
}));

export function setUserSettings(settings: UserSettings | null): void {
    userSettings.set(settings);
}

export function updateSettings(partial: Partial<UserSettings>): void {
    userSettings.update(current => current ? { ...current, ...partial } : null);
}

export function clearUserSettings(): void {
    userSettings.set(null);
}
