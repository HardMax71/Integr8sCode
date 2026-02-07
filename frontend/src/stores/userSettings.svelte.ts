import type { UserSettings, EditorSettings } from '$lib/api';

const DEFAULT_EDITOR_SETTINGS: EditorSettings = {
    theme: 'auto',
    font_size: 14,
    tab_size: 4,
    use_tabs: false,
    word_wrap: true,
    show_line_numbers: true,
};

class UserSettingsStore {
    settings = $state<UserSettings | null>(null);
    editorSettings = $derived<EditorSettings>({ ...DEFAULT_EDITOR_SETTINGS, ...this.settings?.editor });

    setUserSettings(s: UserSettings | null): void {
        this.settings = s;
    }

    clearUserSettings(): void {
        this.settings = null;
    }
}

export const userSettingsStore = new UserSettingsStore();
export const setUserSettings = (s: UserSettings | null) => { userSettingsStore.setUserSettings(s); };
export const clearUserSettings = () => { userSettingsStore.clearUserSettings(); };
