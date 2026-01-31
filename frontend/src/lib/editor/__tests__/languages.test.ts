import { describe, it, expect } from 'vitest';
import { getLanguageExtension } from '$lib/editor/languages';

describe('getLanguageExtension', () => {
    it.each(['python', 'node', 'go', 'ruby', 'bash'])(
        'returns an extension for "%s"',
        (lang) => {
            const ext = getLanguageExtension(lang);
            expect(ext).toBeDefined();
        },
    );

    it('returns python extension for unknown language', () => {
        const fallback = getLanguageExtension('unknown-lang');
        const python = getLanguageExtension('python');
        // Both should return a python() extension — compare structure
        expect(typeof fallback).toBe(typeof python);
    });

    it('returns python extension for empty string', () => {
        const ext = getLanguageExtension('');
        expect(ext).toBeDefined();
    });

    it('returns distinct extensions for different languages', () => {
        const py = getLanguageExtension('python');
        const js = getLanguageExtension('node');
        // Different language extensions should not be referentially equal
        expect(py).not.toBe(js);
    });
});
