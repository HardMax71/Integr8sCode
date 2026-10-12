import { untrack } from 'svelte';
import { mode, setMode, userPrefersMode } from 'mode-watcher';
import { Theme } from '#lib/api/index.ts';

const cycle = Object.values(Theme);

/** mode-watcher stores the choice and keeps the dark class on <html>; its modes are the API's Theme values */
export const themeStore = {
    /** The theme the user picked */
    get value(): Theme {
        return userPrefersMode.current;
    },
    /** Whether the page is dark right now, with "system" resolved against the system */
    get dark(): boolean {
        return mode.current === 'dark';
    },
};

export function setTheme(theme: Theme): void {
    // mode-watcher's persisted setter reads its own state, which would make a calling effect loop
    untrack(() => {
        setMode(theme);
    });
}

export function toggleTheme(): void {
    setTheme(cycle[(cycle.indexOf(themeStore.value) + 1) % cycle.length]!);
}
