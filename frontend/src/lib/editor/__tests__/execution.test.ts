import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ExecutionResult } from '$lib/api';

const mockCreateExecution = vi.fn();
const mockSseFn = vi.fn();

vi.mock('$lib/api', () => ({
    createExecutionApiV1ExecutePost: (...a: unknown[]) => mockCreateExecution(...a),
    executionEventsApiV1EventsExecutionsExecutionIdGet: (...a: unknown[]) => mockSseFn(...a),
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

        it('sets result to null and no error when result_stored has no result', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents({ event_type: 'result_stored' });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toBeNull();
            expect(s.error).toBeNull();
            expect(s.phase).toBe('idle');
        });
    });

    describe('execute → terminal failure sets error', () => {
        it.each(['execution_failed', 'execution_timeout', 'result_failed'])(
            'sets error on %s event',
            async (eventType) => {
                mockCreateExecution.mockResolvedValue({
                    data: { execution_id: 'exec-1', status: 'queued' },
                    error: null,
                });

                mockSseEvents({ event_type: eventType, message: 'something went wrong' });

                const s = createExecutionState();
                await s.execute('x', 'python', '3.12');

                expect(s.error).toBe('something went wrong');
                expect(s.phase).toBe('idle');
            },
        );

        it('uses result from terminal failure event when available', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents({ event_type: 'execution_failed', result: RESULT, message: 'failed' });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toEqual(RESULT);
            expect(s.error).toBe('failed');
        });

        it('uses default message when terminal failure has no message', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents({ event_type: 'execution_failed' });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.error).toBe('Execution failed.');
        });
    });

    describe('execute → stream ends without terminal event', () => {
        it('sets connection lost error', async () => {
            mockCreateExecution.mockResolvedValue({
                data: { execution_id: 'exec-1', status: 'queued' },
                error: null,
            });

            mockSseEvents({ event_type: 'status', status: 'running' });

            const s = createExecutionState();
            await s.execute('x', 'python', '3.12');

            expect(s.error).toBe('Connection to server lost.');
            expect(s.result).toBeNull();
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

            expect(s.error).toBe('Failed to start execution.');
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
