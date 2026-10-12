import { describe, it, expect, beforeEach } from 'vitest';
import { systemPrefersMode, userPrefersMode } from 'mode-watcher';
import { setTheme, themeStore, toggleTheme } from '#stores/theme.svelte.ts';
import { Theme } from '#lib/api/index.ts';

describe('theme', () => {
    beforeEach(() => setTheme(Theme.SYSTEM));

    it.each(Object.values(Theme))('stores %s as the mode-watcher mode', (theme) => {
        setTheme(theme);
        expect(themeStore.value).toBe(theme);
        expect(userPrefersMode.current).toBe(theme);
    });

    it('cycles light, dark, system and back', () => {
        setTheme(Theme.LIGHT);
        const seen = [themeStore.value];
        for (let i = 0; i < 3; i++) {
            toggleTheme();
            seen.push(themeStore.value);
        }
        expect(seen).toEqual([...Object.values(Theme), Theme.LIGHT]);
    });

    it.each([
        [Theme.DARK, true],
        [Theme.LIGHT, false],
    ] as const)('resolves %s to dark=%s', (theme, dark) => {
        setTheme(theme);
        expect(themeStore.dark).toBe(dark);
    });

    it('resolves system to whatever the system prefers', () => {
        setTheme(Theme.SYSTEM);
        expect(themeStore.dark).toBe(systemPrefersMode.current === 'dark');
    });
});
