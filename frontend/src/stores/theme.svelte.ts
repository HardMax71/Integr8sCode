import { Theme } from '#lib/api/index.ts';

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
        this.setTheme(this.value === Theme.LIGHT ? Theme.DARK : this.value === Theme.DARK ? Theme.AUTO : Theme.LIGHT);
    }
}

export const themeStore = new ThemeStore();
export const setTheme = (v: Theme) => {
    themeStore.setTheme(v);
};
export const toggleTheme = () => {
    themeStore.toggleTheme();
};
