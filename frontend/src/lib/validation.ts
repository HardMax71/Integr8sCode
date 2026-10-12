import type { core } from 'zod/mini';
import { fieldTitle } from '#lib/formatters.ts';

/**
 * Our wording for a rule from the API spec, without the field's name, for a form that shows it under the field.
 * Used as the error map of the forms' Zod adapter; undefined leaves Zod's own message.
 * @param issue - The issue Zod raised
 * @returns A sentence such as "Must be at least 8 characters"
 */
export function issueMessage(issue: core.$ZodRawIssue): string | undefined {
    switch (issue.code) {
        case 'too_small':
            if (issue.origin !== 'string') return `Must be at least ${issue.minimum}`;
            return issue.minimum === 1 ? 'Required' : `Must be at least ${issue.minimum} characters`;
        case 'too_big':
            return issue.origin === 'string'
                ? `Must be at most ${issue.maximum} characters`
                : `Must be at most ${issue.maximum}`;
        case 'invalid_format':
            return `Must be a valid ${issue.format}`;
        case 'invalid_type':
            return issue.input === undefined ? 'Required' : `Must be a ${issue.expected}`;
        case 'invalid_union':
            // From optionalText: report the API rule, not the empty alternative
            for (const branch of issue.errors) {
                const [first] = branch;
                if (first && first.code !== 'invalid_value') return issueMessage(first as core.$ZodRawIssue);
            }
            return undefined;
        default:
            return undefined;
    }
}

/**
 * The first problem in a failed parse of a generated Zod schema, as one readable line with the field's name.
 * @param error - The error from `safeParse`
 * @returns A sentence such as "Password must be at least 8 characters"
 */
export function firstIssue(error: core.$ZodError): string {
    const issue = error.issues[0];
    if (!issue) return 'Invalid input';
    const last = issue.path.at(-1);
    const field = typeof last === 'string' ? fieldTitle(last) : 'Value';
    const message = issueMessage(issue as core.$ZodRawIssue);
    if (!message) return `${field}: ${issue.message}`;
    return message === 'Required'
        ? `${field} is required`
        : `${field} ${message.charAt(0).toLowerCase()}${message.slice(1)}`;
}
