import { get } from 'svelte/store';
import { isAuthenticated } from '../stores/auth';
import { setThemeLocal } from '../stores/theme';
import { getCachedSettings, setCachedSettings, updateCachedSetting } from './settings-cache';
import {
    getUserSettingsApiV1UserSettingsGet,
    updateThemeApiV1UserSettingsThemePut,
    updateEditorSettingsApiV1UserSettingsEditorPut,
    type Theme,
    type EditorSettings,
    type UserSettings,
} from './api';

export async function saveThemeSetting(theme: string): Promise<boolean | undefined> {
    if (!get(isAuthenticated)) {
        return;
    }

    try {
        const { error } = await updateThemeApiV1UserSettingsThemePut({
            body: { theme: theme as Theme }
        });

        if (error) {
            console.error('Failed to save theme setting');
            throw error;
        }

        updateCachedSetting('theme', theme);
        console.log('Theme setting saved:', theme);
        return true;
    } catch (err) {
        console.error('Error saving theme setting:', err);
        return false;
    }
}

export async function loadUserSettings(): Promise<UserSettings | undefined> {
    const cached = getCachedSettings();
    if (cached) {
        if (cached.theme) {
            setThemeLocal(cached.theme);
        }
        return cached;
    }

    try {
        const { data, error } = await getUserSettingsApiV1UserSettingsGet({});

        if (error || !data) {
            console.warn('Could not load user settings, using defaults');
            return;
        }

        setCachedSettings(data);

        if (data.theme) {
            setThemeLocal(data.theme);
        }

        return data;
    } catch (err) {
        console.error('Failed to load user settings:', err);
    }
}

export async function saveEditorSettings(editorSettings: EditorSettings): Promise<boolean | undefined> {
    if (!get(isAuthenticated)) {
        return;
    }

    try {
        const { error } = await updateEditorSettingsApiV1UserSettingsEditorPut({
            body: editorSettings
        });

        if (error) {
            console.error('Failed to save editor settings');
            throw error;
        }

        updateCachedSetting('editor', editorSettings);
        console.log('Editor settings saved');
        return true;
    } catch (err) {
        console.error('Error saving editor settings:', err);
        return false;
    }
}
