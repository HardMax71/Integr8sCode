import { describe, it, expect } from 'vitest';
import { STATS_BG_COLORS, STATS_TEXT_COLORS } from '#lib/admin/constants.ts';

describe('admin constants', () => {
    it.each([
        ['green', 'bg-success-soft', 'text-success'],
        ['red', 'bg-danger-soft', 'text-danger'],
        ['yellow', 'bg-warning-soft', 'text-warning'],
        ['blue', 'bg-info-soft', 'text-info'],
        ['purple', 'bg-purple-soft', 'text-purple'],
        ['orange', 'bg-orange-soft', 'text-orange'],
        ['neutral', 'bg-muted', 'text-fg-muted'],
    ] as const)('%s stats use one token for both modes', (key, bg, text) => {
        expect(STATS_BG_COLORS[key]).toBe(bg);
        expect(STATS_TEXT_COLORS[key]).toBe(text);
    });
});
