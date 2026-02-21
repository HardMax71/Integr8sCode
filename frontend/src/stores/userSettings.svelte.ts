import type { UserSettings, EditorSettingsOutput } from '$lib/api';

const FALLBACK_EDITOR_SETTINGS: EditorSettingsOutput = {
    font_size: 14,
    tab_size: 4,
    use_tabs: false,
    word_wrap: true,
    show_line_numbers: true,
};

class UserSettingsStore {
    settings = $state<UserSettings | null>(null);
    editorSettings = $derived<EditorSettingsOutput>(this.settings?.editor ?? FALLBACK_EDITOR_SETTINGS);

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
