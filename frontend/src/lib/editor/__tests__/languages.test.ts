import { describe, it, expect } from 'vitest';
import { EditorState } from '@codemirror/state';
import { language } from '@codemirror/language';
import { loadLanguage } from '#lib/editor/languages.ts';

describe('loadLanguage', () => {
    it.each([
        ['python', 'python'],
        ['node', 'javascript'],
        ['go', 'go'],
        ['ruby', 'ruby'],
        ['bash', 'shell'],
    ])('loads the %s mode', async (lang, name) => {
        const state = EditorState.create({ extensions: await loadLanguage(lang) });
        expect(state.facet(language)?.name).toBe(name);
    });

    it.each(['unknown-lang', ''])('gives "%s" plain text', async (lang) => {
        expect(await loadLanguage(lang)).toEqual([]);
    });
});
