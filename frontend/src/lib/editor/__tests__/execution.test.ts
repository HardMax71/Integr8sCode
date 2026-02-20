import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ExecutionResult } from '$lib/api';

const mockCreateExecution = vi.fn();
const mockSseFn = vi.fn();
const mockGetResult = vi.fn();

vi.mock('$lib/api', () => ({
    createExecutionApiV1ExecutePost: (...a: unknown[]) => mockCreateExecution(...a),
    executionEventsApiV1EventsExecutionsExecutionIdGet: (...a: unknown[]) => mockSseFn(...a),
    getResultApiV1ExecutionsExecutionIdResultGet: (...a: unknown[]) => mockGetResult(...a),
}));

vi.mock('$lib/api-interceptors', () => ({
    getErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

const { createExecutionState } = await import('../execution.svelte');

const RESULT: ExecutionResult = {
    execution_id: 'exec-1',
    status: 'completed',
    stdout: 'hello',
    stderr: '',
    exit_code: 0,
    lang: 'python',
    lang_version: '3.12',
    execution_time: 0.1,
    memory_used_kb: 64,
};

function mockSseEvents(...events: unknown[]) {
    mockSseFn.mockResolvedValue({
        stream: (async function* () {
            for (const e of events) yield e;
        })(),
    });
}

describe('createExecutionState', () => {
    beforeEach(() => {
        mockCreateExecution.mockReset();
        mockSseFn.mockReset();
        mockGetResult.mockReset();
    });

    describe('initial state', () => {
        it.each([
            ['phase', 'idle'],
            ['result', null],
            ['error', null],
            ['isExecuting', false],
        ] as const)('%s is %j', (key, expected) => {
            const s = createExecutionState();
            expect(s[key]).toBe(expected);
        });
    });

    describe('execute → stream result_stored', () => {
        it('yields result from SSE stream', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents(
                { event_type: 'status', status: 'running' },
                { event_type: 'result_stored', result: RESULT },
            );

            const s = createExecutionState();
            await s.execute('print("hi")', 'python', '3.12');

            expect(s.result).toEqual(RESULT);
            expect(s.phase).toBe('idle');
            expect(s.error).toBeNull();
        });
    });

    describe('execute → terminal failure falls back to fetchResult', () => {
        it.each(['execution_failed', 'execution_timeout', 'result_failed'])(
            'fetches result on %s event',
            async (eventType) => {
                mockCreateExecution.mockResolvedValue({
                    data: { execution_id: 'exec-1', status: 'queued' },
                    error: null,
                });

                mockSseEvents({ event_type: eventType });
                mockGetResult.mockResolvedValue({ data: RESULT, error: null });

                const s = createExecutionState();
                await s.execute('x', 'python', '3.12');

                expect(mockGetResult).toHaveBeenCalledOnce();
                expect(s.result).toEqual(RESULT);
            },
        );
    });

    describe('execute → stream ends without terminal event', () => {
        it('falls back to fetchResult', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents({ event_type: 'status', status: 'running' });
            mockGetResult.mockResolvedValue({ data: RESULT, error: null });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(mockGetResult).toHaveBeenCalledOnce();
            expect(s.result).toEqual(RESULT);
        });
    });

    describe('execute → SSE connection failure falls back to fetchResult', () => {
        it('fetches result on SSE error', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseFn.mockRejectedValue(new Error('SSE failed: 500'));
            mockGetResult.mockResolvedValue({ data: RESULT, error: null });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toEqual(RESULT);
        });

        it('sets error when both SSE and fetchResult fail', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseFn.mockRejectedValue(new Error('Unauthorized'));
            mockGetResult.mockResolvedValue({ data: undefined, error: { detail: 'Unauthorized' } });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.error).toBe('Error executing script.');
        });
    });

    describe('execute → API error', () => {
        it('sets error when createExecution fails', async () => {
            mockCreateExecution.mockResolvedValue({
                data: null,
                error: { detail: 'rate limited' },
            });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.error).toBe('Error executing script.');
            expect(s.phase).toBe('idle');
        });
    });

    describe('abort', () => {
        it('resets phase to idle', () => {
            const s = createExecutionState();
            s.abort();
            expect(s.phase).toBe('idle');
        });
    });

    describe('reset', () => {
        it('clears all state', async () => {
            mockCreateExecution.mockResolvedValue({ data: null, error: 'fail' });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            s.reset();
            expect(s.phase).toBe('idle');
            expect(s.result).toBeNull();
            expect(s.error).toBeNull();
        });
    });

    describe('malformed SSE data', () => {
        it('skips non-object events and continues', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents(
                '{broken',
                { event_type: 'result_stored', result: RESULT },
            );

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toEqual(RESULT);
        });
    });
});
