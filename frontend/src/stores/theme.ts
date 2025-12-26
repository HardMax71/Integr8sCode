import { writable, get } from 'svelte/store';

type ThemeValue = 'light' | 'dark' | 'auto';

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

const initialTheme = getInitialTheme();
const { subscribe, set: internalSet, update } = writable<ThemeValue>(initialTheme);

let saveUserSettings: ((partial: { theme?: ThemeValue }) => Promise<boolean>) | null = null;
let isAuthenticatedStore: import('svelte/store').Readable<boolean | null> | null = null;

if (browser) {
    Promise.all([
        import('$lib/user-settings'),
        import('$stores/auth')
    ]).then(([userSettings, auth]) => {
        saveUserSettings = userSettings.saveUserSettings;
        isAuthenticatedStore = auth.isAuthenticated;
    });
}

export const theme = {
    subscribe,
    set: (value: ThemeValue) => {
        internalSet(value);
        if (browser) {
            localStorage.setItem(storageKey, value);
        }
    },
    update
};

function applyTheme(newTheme: ThemeValue): void {
    if (!browser) return;
    const effectiveTheme = newTheme === 'auto' ? getSystemTheme() : newTheme;
    document.documentElement.classList.toggle('dark', effectiveTheme === 'dark');
}

theme.subscribe(applyTheme);

if (browser) {
    applyTheme(initialTheme);
    window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => {
        theme.update(current => {
            if (current === 'auto') applyTheme('auto');
            return current;
        });
    });
}

export function toggleTheme(): void {
    const current = get(theme);
    const next: ThemeValue = current === 'light' ? 'dark' : current === 'dark' ? 'auto' : 'light';
    theme.set(next);
    if (saveUserSettings && isAuthenticatedStore && get(isAuthenticatedStore)) {
        saveUserSettings({ theme: next });
    }
}

export function setTheme(newTheme: ThemeValue): void {
    theme.set(newTheme);
}
