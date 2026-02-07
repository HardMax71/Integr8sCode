export type ThemeValue = 'light' | 'dark' | 'auto';

const browser = typeof window !== 'undefined' && typeof document !== 'undefined';
const defaultTheme: ThemeValue = 'auto';
const storageKey = 'app-theme';

function getSystemTheme(): 'light' | 'dark' {
    if (!browser) return 'light';
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getInitialTheme(): ThemeValue {
    if (!browser) return defaultTheme;
    const stored = localStorage.getItem(storageKey);
    if (stored && ['light', 'dark', 'auto'].includes(stored)) {
        return stored as ThemeValue;
    }
    return defaultTheme;
}

function applyTheme(newTheme: ThemeValue): void {
    if (!browser) return;
    const effectiveTheme = newTheme === 'auto' ? getSystemTheme() : newTheme;
    document.documentElement.classList.toggle('dark', effectiveTheme === 'dark');
}

let saveUserSettingsFn: ((partial: { theme?: ThemeValue }) => Promise<boolean>) | null = null;
let authStoreRef: { isAuthenticated: boolean | null } | null = null;

if (browser) {
    Promise.all([
        import('$lib/user-settings'),
        import('$stores/auth.svelte')
    ]).then(([userSettings, auth]) => {
        saveUserSettingsFn = userSettings.saveUserSettings;
        authStoreRef = auth.authStore;
    });
}

class ThemeStore {
    value = $state<ThemeValue>(getInitialTheme());

    constructor() {
        // Apply initial theme
        if (browser) {
            applyTheme(this.value);
            window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => {
                if (this.value === 'auto') applyTheme('auto');
            });
        }
    }

    setTheme(v: ThemeValue): void {
        this.value = v;
        if (browser) {
            localStorage.setItem(storageKey, v);
        }
        applyTheme(v);
    }

    toggleTheme(): void {
        const next: ThemeValue = this.value === 'light' ? 'dark' : this.value === 'dark' ? 'auto' : 'light';
        this.setTheme(next);
        if (saveUserSettingsFn && authStoreRef && authStoreRef.isAuthenticated) {
            saveUserSettingsFn({ theme: next });
        }
    }
}

export const themeStore = new ThemeStore();
export const setTheme = (v: ThemeValue) => themeStore.setTheme(v);
export const toggleTheme = () => themeStore.toggleTheme();
