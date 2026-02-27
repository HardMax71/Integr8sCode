import { describe, it, expect } from 'vitest';
import { getErrorMessage, unwrap, unwrapOr } from '$lib/api-interceptors';

describe('getErrorMessage', () => {
    it.each([
        ['null', null, undefined, 'An error occurred'],
        ['undefined', undefined, undefined, 'An error occurred'],
        ['zero', 0, undefined, 'An error occurred'],
        ['empty string', '', undefined, 'An error occurred'],
        ['null with custom fallback', null, 'custom', 'custom'],
        ['number', 42, undefined, 'An error occurred'],
        ['boolean', true, undefined, 'An error occurred'],
        ['object without detail/message', { foo: 'bar' }, undefined, 'An error occurred'],
    ] as [string, unknown, string | undefined, string][])('returns fallback for %s', (_label, input, fallback, expected) => {
        expect(getErrorMessage(input, fallback)).toBe(expected);
    });

    it.each([
        ['string error', 'something broke', 'something broke'],
        ['Error instance', new Error('boom'), 'boom'],
        ['object with .detail string', { detail: 'Not found' }, 'Not found'],
        ['ValidationError[] with locs', {
            detail: [
                { loc: ['body', 'email'], msg: 'invalid email', type: 'value_error' },
                { loc: ['body', 'name'], msg: 'required', type: 'value_error' },
            ],
        }, 'email: invalid email, name: required'],
        ['ValidationError[] with empty loc', {
            detail: [{ loc: [], msg: 'bad', type: 'value_error' }],
        }, 'bad'],
        ['ValidationError[] with single loc', {
            detail: [{ loc: ['body'], msg: 'Error', type: 'value_error' }],
        }, 'body: Error'],
    ] as [string, unknown, string][])('extracts message from %s', (_label, input, expected) => {
        expect(getErrorMessage(input)).toBe(expected);
    });
});

describe('unwrap', () => {
    it.each([
        ['number', { data: 42 }, 42],
        ['zero', { data: 0 }, 0],
        ['empty string', { data: '' }, ''],
        ['false', { data: false }, false],
    ] as [string, { data: unknown }, unknown][])('returns data for %s', (_label, result, expected) => {
        expect(unwrap(result)).toBe(expected);
    });

    it.each([
        ['error present', { data: 42, error: new Error('fail') }],
        ['data undefined', {}],
    ] as [string, { data?: unknown; error?: unknown }][])('throws when %s', (_label, result) => {
        expect(() => unwrap(result)).toThrow();
    });
});

describe('unwrapOr', () => {
    it.each([
        ['data present', { data: 'value' }, 'fb', 'value'],
        ['data is 0', { data: 0 }, 99, 0],
        ['data is empty string', { data: '' }, 'fb', ''],
        ['error present', { data: 'v', error: new Error() }, 'fb', 'fb'],
        ['data undefined', {}, 'fb', 'fb'],
    ] as [string, { data?: unknown; error?: unknown }, unknown, unknown][])('returns correct value when %s', (_label, result, fallback, expected) => {
        expect(unwrapOr(result, fallback)).toBe(expected);
    });
});
