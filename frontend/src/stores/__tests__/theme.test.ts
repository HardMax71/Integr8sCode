import { describe, it, expect, beforeEach } from 'vitest';
import { systemPrefersMode, userPrefersMode } from 'mode-watcher';
import { setTheme, themeStore, toggleTheme } from '#stores/theme.svelte.ts';

describe('theme', () => {
    beforeEach(() => setTheme('system'));

    it.each(['light', 'dark', 'system'] as const)('stores %s as the mode-watcher mode', (theme) => {
        setTheme(theme);
        expect(themeStore.value).toBe(theme);
        expect(userPrefersMode.current).toBe(theme);
    });

    it('cycles light, dark, system and back', () => {
        setTheme('light');
        const seen = [themeStore.value];
        for (let i = 0; i < 3; i++) {
            toggleTheme();
            seen.push(themeStore.value);
        }
        expect(seen).toEqual(['light', 'dark', 'system', 'light']);
    });

    it.each([
        ['dark', true],
        ['light', false],
    ] as const)('resolves %s to dark=%s', (theme, dark) => {
        setTheme(theme);
        expect(themeStore.dark).toBe(dark);
    });

    it('resolves system to whatever the system prefers', () => {
        setTheme('system');
        expect(themeStore.dark).toBe(systemPrefersMode.current === 'dark');
    });
});
