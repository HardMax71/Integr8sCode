import { describe, it, expect } from 'vitest';
import { zSystemSettingsSchemaInput, zUserCreate } from '#lib/api/index.ts';
import { firstIssue } from '#lib/validation.ts';

function issueFor(result: { success: boolean; error?: unknown }): string {
    if (result.success) throw new Error('expected the parse to fail');
    return firstIssue(result.error as Parameters<typeof firstIssue>[0]);
}

describe('firstIssue', () => {
    it.each([
        [
            'a short password',
            zUserCreate.safeParse({ username: 'u', email: 'u@example.com', password: 'short' }),
            'Password must be at least 8 characters',
        ],
        [
            'an invalid email',
            zUserCreate.safeParse({ username: 'u', email: 'nope', password: 'password123' }),
            'Email must be a valid email',
        ],
        [
            'a number above its maximum',
            zSystemSettingsSchemaInput.safeParse({ max_timeout_seconds: 99999 }),
            'Max Timeout Seconds must be at most 3600',
        ],
        [
            'a number below its minimum',
            zSystemSettingsSchemaInput.safeParse({ max_login_attempts: 1 }),
            'Max Login Attempts must be at least 3',
        ],
        [
            'a missing required field',
            zUserCreate.safeParse({ email: 'u@example.com', password: 'password123' }),
            'Username is required',
        ],
    ])('phrases %s from the generated schema', (_name, result, expected) => {
        expect(issueFor(result)).toBe(expected);
    });
});
