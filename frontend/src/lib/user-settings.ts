import { get } from 'svelte/store';
import { isAuthenticated } from '../stores/auth';
import { setTheme } from '../stores/theme';
import { setUserSettings } from '../stores/userSettings';
import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    type UserSettings,
    type UserSettingsUpdate,
} from './api';
import { unwrap } from './api-interceptors';

export async function loadUserSettings(): Promise<UserSettings | undefined> {
    try {
        const { data, error } = await getUserSettingsApiV1UserSettingsGet({});

        if (error || !data) {
            console.warn('Could not load user settings, using defaults');
            return;
        }

        setUserSettings(data);

        if (data.theme) {
            setTheme(data.theme);
        }

        return data;
    } catch (err) {
        console.error('Failed to load user settings:', err);
    }
}

export async function saveUserSettings(partial: UserSettingsUpdate): Promise<boolean> {
    if (!get(isAuthenticated)) return false;

    try {
        const data = unwrap(await updateUserSettingsApiV1UserSettingsPut({ body: partial }));
        setUserSettings(data);

        if (data.theme) {
            setTheme(data.theme);
        }

        return true;
    } catch (err) {
        console.error('Error saving user settings:', err);
        return false;
    }
}
