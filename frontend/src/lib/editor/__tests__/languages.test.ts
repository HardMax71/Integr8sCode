import { describe, it, expect } from 'vitest';
import { loadLanguage } from '#lib/editor/languages.ts';

describe('loadLanguage', () => {
    it.each(['python', 'node', 'go', 'ruby', 'bash'])('loads a mode for "%s"', async (lang) => {
        expect(await loadLanguage(lang)).not.toEqual([]);
    });

    it.each(['unknown-lang', ''])('gives "%s" plain text', async (lang) => {
        expect(await loadLanguage(lang)).toEqual([]);
    });

    it('loads distinct modes for different languages', async () => {
        const [py, js] = await Promise.all([loadLanguage('python'), loadLanguage('node')]);
        expect(py).not.toBe(js);
    });
});
