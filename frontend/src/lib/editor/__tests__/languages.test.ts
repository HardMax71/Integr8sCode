import { describe, it, expect } from 'vitest';
import { getLanguageExtension } from '#lib/editor/languages.ts';

describe('getLanguageExtension', () => {
    it.each(['python', 'node', 'go', 'ruby', 'bash'])('returns an extension for "%s"', (lang) => {
        const ext = getLanguageExtension(lang);
        expect(ext).toBeDefined();
    });

    it.each(['unknown-lang', ''])('returns no extension for "%s"', (lang) => {
        expect(getLanguageExtension(lang)).toEqual([]);
    });

    it('returns distinct extensions for different languages', () => {
        const py = getLanguageExtension('python');
        const js = getLanguageExtension('node');
        expect(py).not.toBe(js);
    });
});
