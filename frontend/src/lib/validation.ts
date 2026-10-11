import type { z } from 'zod';
import { formatEnumLabel } from '$lib/formatters';

/**
 * The first problem in a failed parse of a generated Zod schema, as one readable line.
 * The rule comes from the API spec; only the wording is ours.
 * @param error - The error from `safeParse`
 * @returns A sentence such as "Password must be at least 8 characters"
 */
export function firstIssue(error: z.ZodError): string {
    const issue = error.issues[0];
    if (!issue) return 'Invalid input';
    const last = issue.path[issue.path.length - 1];
    const field = typeof last === 'string' ? formatEnumLabel(last) : 'Value';
    switch (issue.code) {
        case 'too_small':
            return issue.origin === 'string'
                ? `${field} must be at least ${issue.minimum} characters`
                : `${field} must be at least ${issue.minimum}`;
        case 'too_big':
            return issue.origin === 'string'
                ? `${field} must be at most ${issue.maximum} characters`
                : `${field} must be at most ${issue.maximum}`;
        case 'invalid_format':
            return `${field} must be a valid ${issue.format}`;
        default:
            return `${field}: ${issue.message}`;
    }
}
