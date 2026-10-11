import { readFileSync } from 'node:fs';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
    formatTimestamp,
    formatDateOnly,
    formatTimeOnly,
    formatDuration,
    formatDurationBetween,
    formatRelativeTime,
    truncate,
    fieldTitle,
    formatBoolean,
} from '#lib/formatters.ts';

const LOCALE_OPTS_DATETIME: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
};
const LOCALE_OPTS_DATE: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
const LOCALE_OPTS_TIME: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit' };

describe('formatTimestamp', () => {
    it.each([null, undefined, new Date('garbage')])('returns N/A for %j', (input) => {
        expect(formatTimestamp(input)).toBe('N/A');
    });

    it('formats the date and time in the browser locale', () => {
        const date = new Date('2025-01-15T14:30:00Z');
        expect(formatTimestamp(date)).toBe(date.toLocaleString(undefined, LOCALE_OPTS_DATETIME));
    });
});

describe('formatDateOnly', () => {
    it.each([null, undefined, new Date('garbage')])('returns N/A for %j', (input) => {
        expect(formatDateOnly(input)).toBe('N/A');
    });

    it('formats the date in the browser locale', () => {
        const date = new Date('2025-01-15T14:30:00Z');
        expect(formatDateOnly(date)).toBe(date.toLocaleDateString(undefined, LOCALE_OPTS_DATE));
    });
});

describe('formatTimeOnly', () => {
    it.each([null, undefined, new Date('garbage')])('returns N/A for %j', (input) => {
        expect(formatTimeOnly(input)).toBe('N/A');
    });

    it('formats the time in the browser locale', () => {
        const date = new Date(2025, 0, 15, 9, 5);
        expect(formatTimeOnly(date)).toBe(date.toLocaleTimeString(undefined, LOCALE_OPTS_TIME));
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
        [null, new Date('2025-01-01T12:00:00Z')],
        [new Date('2025-01-01T12:00:00Z'), null],
        [new Date('garbage'), new Date('2025-01-01T12:00:00Z')],
    ])('returns N/A for (%j, %j)', (start, end) => {
        expect(formatDurationBetween(start, end)).toBe('N/A');
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
        [new Date(2025, 6, 15, 11, 59, 30), 'just now'], // 30s ago
        [new Date(2025, 6, 15, 11, 55, 0), '5m ago'], // 5m ago
        [new Date(2025, 6, 15, 9, 0, 0), '3h ago'], // 3h ago
        [new Date(2025, 6, 13, 12, 0, 0), '2d ago'], // 2d ago
    ])('formats %j as %j', (date, expected) => {
        expect(formatRelativeTime(date)).toBe(expected);
    });

    it('returns formatted date for >7 days ago', () => {
        const result = formatRelativeTime(new Date(2025, 6, 1));
        expect(result).not.toMatch(/ago$/);
        expect(result).not.toBe('N/A');
    });

    it('returns formatted date for future dates', () => {
        const result = formatRelativeTime(new Date(2025, 6, 20));
        expect(result).not.toMatch(/ago$/);
    });

    it.each([null, new Date('not-valid')])('returns N/A for %j', (input) => {
        expect(formatRelativeTime(input)).toBe('N/A');
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

describe('fieldTitle', () => {
    const spec = JSON.parse(readFileSync('../docs/reference/openapi.json', 'utf8')) as {
        components: { schemas: Record<string, { properties?: Record<string, { title?: string }> }> };
    };
    // FastAPI's own validation error model titles its fields ("msg" is "Message")
    const framework = new Set(['ValidationError', 'HTTPValidationError']);
    const titled = Object.entries(spec.components.schemas)
        .filter(([name]) => !framework.has(name))
        .flatMap(([, schema]) => Object.entries(schema.properties ?? {}))
        .flatMap(([key, prop]) => (prop.title ? [{ key, title: prop.title }] : []));

    it('titles every key the way the spec does', () => {
        expect(titled.length).toBeGreaterThan(100);
        for (const { key, title } of titled) expect(fieldTitle(key)).toBe(title);
    });

    it.each([
        ['created_at', 'Created At'],
        ['is_active', 'Is Active'],
        ['clk_tck_hertz', 'Clk Tck Hertz'],
        ['peak_memory_kb', 'Peak Memory Kb'],
    ])('%s -> %s', (key, expected) => {
        expect(fieldTitle(key)).toBe(expected);
    });
});

describe('formatBoolean', () => {
    it.each([
        [true, 'Yes'],
        [false, 'No'],
    ])('%s -> %s', (value, expected) => {
        expect(formatBoolean(value)).toBe(expected);
    });
});
