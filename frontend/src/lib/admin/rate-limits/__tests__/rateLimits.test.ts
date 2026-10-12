import { describe, it, expect } from 'vitest';
import { EndpointGroup, zRateLimitRuleRequest } from '#lib/api/index.ts';
import { getGroupColor, createEmptyRule } from '#lib/admin/rate-limits/rateLimits.ts';

describe('rateLimits', () => {
    describe('getGroupColor', () => {
        it.each(Object.values(EndpointGroup))('returns a dark-mode color string for %s', (group) => {
            const color = getGroupColor(group);
            expect(color).toBeDefined();
            expect(color).toContain('dark:');
        });

        it.each([
            [EndpointGroup.EXECUTION, 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200'],
            [EndpointGroup.ADMIN, 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'],
            [EndpointGroup.API, 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-200'],
        ])('returns correct color for %s', (group, expected) => {
            expect(getGroupColor(group)).toBe(expected);
        });
    });

    describe('createEmptyRule', () => {
        it('starts from the spec defaults, with starting values for the required fields', () => {
            expect(createEmptyRule()).toEqual(
                zRateLimitRuleRequest.parse({
                    endpoint_pattern: '',
                    group: EndpointGroup.API,
                    requests: 60,
                    window_seconds: 60,
                }),
            );
        });

        it('returns new object each time', () => {
            expect(createEmptyRule()).not.toBe(createEmptyRule());
        });
    });
});
