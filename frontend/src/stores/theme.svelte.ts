import { Theme } from '#lib/api/index.ts';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('Theme');

const browser = typeof window !== 'undefined' && typeof document !== 'undefined';
const defaultTheme: Theme = Theme.AUTO;
const storageKey = 'app-theme';

function getSystemTheme(): 'light' | 'dark' {
    if (!browser) return 'light';
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getInitialTheme(): Theme {
    if (!browser) return defaultTheme;
    const stored = localStorage.getItem(storageKey);
    if (stored && (Object.values(Theme) as string[]).includes(stored)) {
        return stored as Theme;
    }
    return defaultTheme;
}

function applyTheme(newTheme: Theme): void {
    if (!browser) return;
    const effectiveTheme = newTheme === Theme.AUTO ? getSystemTheme() : newTheme;
    document.documentElement.classList.toggle('dark', effectiveTheme === 'dark');
}

let saveUserSettingsFn: ((partial: { theme?: Theme }) => Promise<boolean>) | null = null;
let authStoreRef: { isAuthenticated: boolean | null } | null = null;

if (browser) {
    void Promise.all([import('#lib/user-settings.ts'), import('#stores/auth.svelte.ts')]).then(
        ([userSettings, auth]) => {
            saveUserSettingsFn = userSettings.saveUserSettings;
            authStoreRef = auth.authStore;
        },
    );
}

class ThemeStore {
    value = $state<Theme>(getInitialTheme());

    constructor() {
        // Apply initial theme
        if (browser) {
            applyTheme(this.value);
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                if (this.value === Theme.AUTO) applyTheme(Theme.AUTO);
            });
        }
    }

    setTheme(v: Theme): void {
        this.value = v;
        if (browser) {
            localStorage.setItem(storageKey, v);
        }
        applyTheme(v);
    }

    toggleTheme(): void {
        const next: Theme =
            this.value === Theme.LIGHT ? Theme.DARK : this.value === Theme.DARK ? Theme.AUTO : Theme.LIGHT;
        this.setTheme(next);
        if (saveUserSettingsFn && authStoreRef && authStoreRef.isAuthenticated) {
            void saveUserSettingsFn({ theme: next }).catch((err: unknown) => {
                log.warn('Failed to persist theme setting', err);
            });
        }
    }
}

export const themeStore = new ThemeStore();
export const setTheme = (v: Theme) => {
    themeStore.setTheme(v);
};
export const toggleTheme = () => {
    themeStore.toggleTheme();
};
