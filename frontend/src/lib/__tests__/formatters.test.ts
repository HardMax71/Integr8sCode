import { describe, it, expect, vi, beforeEach } from 'vitest';
import { format, parseISO } from 'date-fns';
import {
    formatTimestamp,
    formatDateOnly,
    formatTimeOnly,
    formatDuration,
    formatDurationBetween,
    formatRelativeTime,
    truncate,
} from '$lib/formatters';

describe('formatTimestamp', () => {
    it.each([null, undefined, 'garbage', ''] as const)('returns N/A for %j', (input) => {
        expect(formatTimestamp(input as string | null | undefined)).toBe('N/A');
    });

    it('formats ISO string with PPpp', () => {
        const iso = '2025-01-15T14:30:00Z';
        const expected = format(parseISO(iso), 'PPpp');
        expect(formatTimestamp(iso)).toBe(expected);
    });

    it('accepts Date object', () => {
        const date = new Date(2025, 0, 15);
        expect(formatTimestamp(date)).toBe(format(date, 'PPpp'));
    });
});

describe('formatDateOnly', () => {
    it.each([null, undefined, 'garbage', ''] as const)('returns N/A for %j', (input) => {
        expect(formatDateOnly(input as string | null | undefined)).toBe('N/A');
    });

    it('formats ISO string with PP', () => {
        const iso = '2025-01-15T14:30:00Z';
        const expected = format(parseISO(iso), 'PP');
        expect(formatDateOnly(iso)).toBe(expected);
    });

    it('accepts Date object', () => {
        const date = new Date(2025, 0, 15);
        expect(formatDateOnly(date)).toBe(format(date, 'PP'));
    });
});

describe('formatTimeOnly', () => {
    it.each([null, undefined, 'garbage', ''] as const)('returns N/A for %j', (input) => {
        expect(formatTimeOnly(input as string | null | undefined)).toBe('N/A');
    });

    it('formats ISO string with pp', () => {
        const iso = '2025-01-15T14:30:00Z';
        const expected = format(parseISO(iso), 'pp');
        expect(formatTimeOnly(iso)).toBe(expected);
    });

    it('accepts Date object', () => {
        const date = new Date(2025, 0, 15, 9, 5);
        expect(formatTimeOnly(date)).toBe(format(date, 'pp'));
    });
});

describe('formatDuration', () => {
    it.each([
        [0, '0ms'],
        [0.5, '500ms'],
        [30, '30.0s'],
        [90, '1m 30s'],
        [120, '2m'],
        [3660, '1h 1m'],
        [3600, '1h'],
    ])('formats %d seconds as %j', (input, expected) => {
        expect(formatDuration(input)).toBe(expected);
    });

    it.each([null, undefined, -5])('returns N/A for %j', (input) => {
        expect(formatDuration(input as number | null | undefined)).toBe('N/A');
    });
});

describe('formatDurationBetween', () => {
    it('computes duration between two timestamps', () => {
        const start = new Date(2025, 0, 1, 12, 0, 0);
        const end = new Date(2025, 0, 1, 12, 1, 30);
        expect(formatDurationBetween(start, end)).toBe('1m 30s');
    });

    it.each([
        [null, '2025-01-01T12:00:00Z'],
        ['2025-01-01T12:00:00Z', null],
        ['garbage', '2025-01-01T12:00:00Z'],
    ] as const)('returns N/A for (%j, %j)', (start, end) => {
        expect(formatDurationBetween(
            start as string | null | undefined,
            end as string | null | undefined,
        )).toBe('N/A');
    });

    it('returns N/A when end is before start', () => {
        const start = new Date(2025, 0, 1, 13, 0, 0);
        const end = new Date(2025, 0, 1, 12, 0, 0);
        expect(formatDurationBetween(start, end)).toBe('N/A');
    });
});

describe('formatRelativeTime', () => {
    beforeEach(() => {
        vi.setSystemTime(new Date(2025, 6, 15, 12, 0, 0));
    });

    it.each([
        [new Date(2025, 6, 15, 11, 59, 30), 'just now'],  // 30s ago
        [new Date(2025, 6, 15, 11, 55, 0), '5m ago'],      // 5m ago
        [new Date(2025, 6, 15, 9, 0, 0), '3h ago'],        // 3h ago
        [new Date(2025, 6, 13, 12, 0, 0), '2d ago'],       // 2d ago
    ])('formats %j as %j', (date, expected) => {
        expect(formatRelativeTime(date.toISOString())).toBe(expected);
    });

    it('returns formatted date for >7 days ago', () => {
        const result = formatRelativeTime(new Date(2025, 6, 1).toISOString());
        expect(result).not.toMatch(/ago$/);
        expect(result).not.toBe('N/A');
    });

    it('returns formatted date for future dates', () => {
        const result = formatRelativeTime(new Date(2025, 6, 20).toISOString());
        expect(result).not.toMatch(/ago$/);
    });

    it.each([null, 'not-valid'])('returns N/A for %j', (input) => {
        expect(formatRelativeTime(input as string | null | undefined)).toBe('N/A');
    });
});

describe('truncate', () => {
    it.each([
        ['hello', 50, 'hello'],
        ['12345', 5, '12345'],
        [null, 50, ''],
        ['', 50, ''],
    ] as const)('truncate(%j, %d) → %j', (str, max, expected) => {
        expect(truncate(str as string | null | undefined, max)).toBe(expected);
    });

    it('truncates long string with ellipsis', () => {
        const result = truncate('a'.repeat(60), 50);
        expect(result).toHaveLength(50);
        expect(result).toMatch(/\.\.\.$/);
    });

    it('respects custom maxLength', () => {
        expect(truncate('abcdefghij', 7)).toBe('abcd...');
    });
});
