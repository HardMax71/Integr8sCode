import { describe, it, expect } from 'vitest';
import { EndpointGroup } from '#lib/api/index.ts';
import { getGroupColor } from '#lib/admin/rate-limits/rateLimits.ts';

describe('rateLimits', () => {
    describe('getGroupColor', () => {
        it.each([
            [EndpointGroup.EXECUTION, 'bg-purple-soft text-purple'],
            [EndpointGroup.ADMIN, 'bg-danger-soft text-danger'],
            [EndpointGroup.API, 'bg-muted text-fg'],
        ])('returns correct color for %s', (group, expected) => {
            expect(getGroupColor(group)).toBe(expected);
        });
    });
});
