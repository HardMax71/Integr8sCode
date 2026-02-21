import { authStore } from '$stores/auth.svelte';
import { setTheme } from '$stores/theme.svelte';
import { setUserSettings } from '$stores/userSettings.svelte';
import {
    getUserSettingsApiV1UserSettingsGet,
    updateUserSettingsApiV1UserSettingsPut,
    type UserSettings,
    type UserSettingsUpdate,
} from '$lib/api';

export async function loadUserSettings(): Promise<UserSettings | undefined> {
    const { data, error } = await getUserSettingsApiV1UserSettingsGet({});

    if (error || !data) return;

    setUserSettings(data);
    setTheme(data.theme);

    return data;
}

export async function saveUserSettings(partial: UserSettingsUpdate): Promise<boolean> {
    if (!authStore.isAuthenticated) return false;

    const { data } = await updateUserSettingsApiV1UserSettingsPut({ body: partial });
    if (!data) return false;

    setUserSettings(data);
    setTheme(data.theme);

    return true;
}
