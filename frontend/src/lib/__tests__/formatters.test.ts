import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
    formatDate,
    formatTimestamp,
    formatDuration,
    formatDurationBetween,
    formatRelativeTime,
    formatBytes,
    formatNumber,
    truncate,
} from '../formatters';

describe('formatDate', () => {
    it.each([
        [null, 'N/A'],
        [undefined, 'N/A'],
        ['', 'N/A'],
        ['not-a-date', 'N/A'],
    ] as const)('returns %j for %j input', (input, expected) => {
        expect(formatDate(input as string | null | undefined)).toBe(expected);
    });

    it('formats ISO string to DD/MM/YYYY HH:mm', () => {
        const date = new Date(2025, 0, 15, 14, 30);
        expect(formatDate(date.toISOString())).toBe('15/01/2025 14:30');
    });

    it('accepts Date object', () => {
        expect(formatDate(new Date(2025, 5, 1, 9, 5))).toBe('01/06/2025 09:05');
    });
});

describe('formatTimestamp', () => {
    it.each([null, undefined, 'garbage'] as const)('returns N/A for %j', (input) => {
        expect(formatTimestamp(input as string | null | undefined)).toBe('N/A');
    });

    it('formats ISO string', () => {
        const date = new Date(2025, 0, 15);
        expect(formatTimestamp(date.toISOString())).toBe(date.toLocaleString());
    });

    it('accepts custom Intl options', () => {
        const date = new Date(2025, 0, 15);
        const opts: Intl.DateTimeFormatOptions = { year: 'numeric' };
        const expected = new Intl.DateTimeFormat(undefined, opts).format(date);
        expect(formatTimestamp(date.toISOString(), opts)).toBe(expected);
    });

    it('accepts Date object', () => {
        const date = new Date(2025, 0, 15);
        expect(formatTimestamp(date)).toBe(date.toLocaleString());
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
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2025, 6, 15, 12, 0, 0));
    });
    afterEach(() => vi.useRealTimers());

    it.each([
        [new Date(2025, 6, 15, 11, 59, 30), 'just now'],  // 30s ago
        [new Date(2025, 6, 15, 11, 55, 0), '5m ago'],      // 5m ago
        [new Date(2025, 6, 15, 9, 0, 0), '3h ago'],        // 3h ago
        [new Date(2025, 6, 13, 12, 0, 0), '2d ago'],       // 2d ago
    ])('formats %j as %j', (date, expected) => {
        expect(formatRelativeTime(date.toISOString())).toBe(expected);
    });

    it('returns locale date for >7 days ago', () => {
        const result = formatRelativeTime(new Date(2025, 6, 1).toISOString());
        expect(result).not.toMatch(/ago$/);
        expect(result).not.toBe('N/A');
    });

    it('returns locale date for future dates', () => {
        const result = formatRelativeTime(new Date(2025, 6, 20).toISOString());
        expect(result).not.toMatch(/ago$/);
    });

    it.each([null, 'not-valid'])('returns N/A for %j', (input) => {
        expect(formatRelativeTime(input as string | null | undefined)).toBe('N/A');
    });
});

describe('formatBytes', () => {
    it.each([
        [0, undefined, '0 B'],
        [500, undefined, '500 B'],
        [1536, undefined, '1.5 KB'],
        [1048576, undefined, '1 MB'],
        [1536, 0, '2 KB'],
    ] as const)('formats %d bytes (decimals=%j) as %j', (bytes, decimals, expected) => {
        expect(formatBytes(bytes, decimals)).toBe(expected);
    });

    it.each([null, undefined, -1])('returns N/A for %j', (input) => {
        expect(formatBytes(input as number | null | undefined)).toBe('N/A');
    });
});

describe('formatNumber', () => {
    it('formats zero', () => {
        const expected = new Intl.NumberFormat().format(0);
        expect(formatNumber(0)).toBe(expected);
    });

    it('formats with locale separators', () => {
        const expected = new Intl.NumberFormat().format(1234567);
        expect(formatNumber(1234567)).toBe(expected);
    });

    it.each([null, undefined])('returns N/A for %j', (input) => {
        expect(formatNumber(input as number | null | undefined)).toBe('N/A');
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
