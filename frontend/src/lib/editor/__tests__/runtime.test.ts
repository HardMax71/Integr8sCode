import { describe, it, expect } from 'vitest';
import { pickRuntime } from '#lib/editor/runtime.ts';

const OFFERED = {
    python: { versions: ['3.14', '3.13'], file_ext: 'py' },
    go: { versions: ['1.27'], file_ext: 'go' },
};

describe('pickRuntime', () => {
    it.each([
        {
            name: 'keeps an offered runtime',
            lang: 'python',
            lang_version: '3.13',
            expected: { lang: 'python', lang_version: '3.13' },
        },
        {
            name: "takes the language's newest version for a dropped one",
            lang: 'python',
            lang_version: '3.7',
            expected: { lang: 'python', lang_version: '3.14' },
        },
        {
            name: 'takes the first language for a dropped one',
            lang: 'cobol',
            lang_version: '85',
            expected: { lang: 'python', lang_version: '3.14' },
        },
    ])('$name', ({ lang, lang_version, expected }) => {
        expect(pickRuntime({ lang, lang_version }, OFFERED)).toEqual(expected);
    });

    it('keeps the runtime while nothing is offered yet', () => {
        expect(pickRuntime({ lang: 'go', lang_version: '1.26' }, {})).toEqual({ lang: 'go', lang_version: '1.26' });
    });
});
