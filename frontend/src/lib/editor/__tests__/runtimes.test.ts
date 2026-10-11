import { describe, it, expect } from 'vitest';
import { newestVersion } from '#lib/editor/runtimes.ts';

describe('newestVersion', () => {
    it.each([
        { versions: ['3.11', '3.14', '3.9', '3.13'], expected: '3.14' },
        { versions: ['22', '26', '24'], expected: '26' },
        { versions: ['3.3', '4.0', '3.4'], expected: '4.0' },
        { versions: ['1.26', '1.27'], expected: '1.27' },
        { versions: ['5.3'], expected: '5.3' },
    ])('picks $expected from $versions', ({ versions, expected }) => {
        expect(newestVersion(versions)).toBe(expected);
    });

    it('returns undefined for an empty list', () => {
        expect(newestVersion([])).toBeUndefined();
    });

    it('does not reorder the input', () => {
        const versions = ['3.12', '3.14'];
        newestVersion(versions);
        expect(versions).toEqual(['3.12', '3.14']);
    });
});
