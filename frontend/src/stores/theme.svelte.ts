import { untrack } from 'svelte';
import { mode, setMode, userPrefersMode } from 'mode-watcher';
import { Theme } from '#lib/api/index.ts';

// The API calls following the system "auto"; mode-watcher calls it "system"
const toMode = { [Theme.LIGHT]: 'light', [Theme.DARK]: 'dark', [Theme.AUTO]: 'system' } as const;
const fromMode = { light: Theme.LIGHT, dark: Theme.DARK, system: Theme.AUTO } as const;
const cycle: Theme[] = [Theme.LIGHT, Theme.DARK, Theme.AUTO];

/** mode-watcher stores the choice and keeps the dark class on <html>; this maps it to the API's Theme */
export const themeStore = {
    /** The theme the user picked */
    get value(): Theme {
        return fromMode[userPrefersMode.current];
    },
    /** Whether the page is dark right now, with "auto" resolved against the system */
    get dark(): boolean {
        return mode.current === 'dark';
    },
};

export function setTheme(theme: Theme): void {
    // mode-watcher's persisted setter reads its own state, which would make a calling effect loop
    untrack(() => setMode(toMode[theme]));
}

export function toggleTheme(): void {
    setTheme(cycle[(cycle.indexOf(themeStore.value) + 1) % cycle.length]!);
}
