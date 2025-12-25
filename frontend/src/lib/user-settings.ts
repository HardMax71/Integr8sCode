import { get } from 'svelte/store';
import { isAuthenticated } from '../stores/auth';
import { setThemeLocal } from '../stores/theme';
import { setUserSettings, updateSettings } from '../stores/userSettings';
import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    type UserSettings,
    type UserSettingsUpdate,
} from './api';

export async function loadUserSettings(): Promise<UserSettings | undefined> {
    try {
        const { data, error } = await getUserSettingsApiV1UserSettingsGet({});

        if (error || !data) {
            console.warn('Could not load user settings, using defaults');
            return;
        }

        setUserSettings(data);

        if (data.theme) {
            setThemeLocal(data.theme);
        }

        return data;
    } catch (err) {
        console.error('Failed to load user settings:', err);
    }
}

export async function saveUserSettings(partial: UserSettingsUpdate): Promise<boolean> {
    if (!get(isAuthenticated)) return false;

    try {
        const { error } = await updateUserSettingsApiV1UserSettingsPut({ body: partial });

        if (error) {
            console.error('Failed to save user settings:', error);
            return false;
        }

        updateSettings(partial as Partial<UserSettings>);

        if (partial.theme) {
            setThemeLocal(partial.theme);
        }

        return true;
    } catch (err) {
        console.error('Error saving user settings:', err);
        return false;
    }
}
