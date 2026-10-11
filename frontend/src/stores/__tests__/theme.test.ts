import { describe, it, expect, beforeEach } from 'vitest';
import { systemPrefersMode, userPrefersMode } from 'mode-watcher';
import { setTheme, themeStore, toggleTheme } from '#stores/theme.svelte.ts';

describe('theme', () => {
    beforeEach(() => setTheme('auto'));

    it.each([
        ['light', 'light'],
        ['dark', 'dark'],
        ['auto', 'system'],
    ] as const)('stores %s as the mode-watcher mode %s', (theme, mode) => {
        setTheme(theme);
        expect(themeStore.value).toBe(theme);
        expect(userPrefersMode.current).toBe(mode);
    });

    it('cycles light, dark, auto and back', () => {
        setTheme('light');
        const seen = [themeStore.value];
        for (let i = 0; i < 3; i++) {
            toggleTheme();
            seen.push(themeStore.value);
        }
        expect(seen).toEqual(['light', 'dark', 'auto', 'light']);
    });

    it.each([
        ['dark', true],
        ['light', false],
    ] as const)('resolves %s to dark=%s', (theme, dark) => {
        setTheme(theme);
        expect(themeStore.dark).toBe(dark);
    });

    it('resolves auto to whatever the system prefers', () => {
        setTheme('auto');
        expect(themeStore.dark).toBe(systemPrefersMode.current === 'dark');
    });
});
