import { authStore } from '$stores/auth.svelte';
import { setTheme } from '$stores/theme.svelte';
import { setUserSettings } from '$stores/userSettings.svelte';
import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    type UserSettings,
    type UserSettingsUpdate,
} from '$lib/api';
import { unwrap } from '$lib/api-interceptors';

export async function loadUserSettings(): Promise<UserSettings | undefined> {
    try {
        const { data, error } = await getUserSettingsApiV1UserSettingsGet({});

        if (error || !data) {
            console.warn('Could not load user settings, using defaults');
            return;
        }

        setUserSettings(data);

        setTheme(data.theme);

        return data;
    } catch (err) {
        console.error('Failed to load user settings:', err);
        return undefined;
    }
}

export async function saveUserSettings(partial: UserSettingsUpdate): Promise<boolean> {
    if (!authStore.isAuthenticated) return false;

    try {
        const data = unwrap(await updateUserSettingsApiV1UserSettingsPut({ body: partial }));
        setUserSettings(data);

        setTheme(data.theme);

        return true;
    } catch (err) {
        console.error('Error saving user settings:', err);
        return false;
    }
}
