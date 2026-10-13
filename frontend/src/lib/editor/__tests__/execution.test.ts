import { describe, it, expect, vi } from 'vitest';
import {
    createExecutionApiV1ExecutePost,
    executionEventsApiV1EventsExecutionsExecutionIdGet,
    type SseExecutionEventSchema,
} from '#lib/api/index.ts';
import { createExecutionState } from '#lib/editor/execution.svelte.ts';
import { captureLogs, createInQueryContext, mockApi, mockStreamEvents } from '#test/test-utils.ts';
import { fakeExecutionResult } from '#lib/api/@faker-js/faker.gen.ts';

const mockSseFn = vi.mocked(executionEventsApiV1EventsExecutionsExecutionIdGet);

const event = (
    fields: Partial<SseExecutionEventSchema> & Pick<SseExecutionEventSchema, 'event_type'>,
): SseExecutionEventSchema => ({
    execution_id: 'exec-1',
    timestamp: null,
    event_id: null,
    status: null,
    result: null,
    ...fields,
});

function createState() {
    return createInQueryContext(createExecutionState).value;
}

function mockStarted() {
    mockApi(createExecutionApiV1ExecutePost).ok({ execution_id: 'exec-1', status: 'queued' });
}

function mockSseEvents(...events: SseExecutionEventSchema[]) {
    mockStreamEvents(executionEventsApiV1EventsExecutionsExecutionIdGet, ...events);
}

describe('createExecutionState', () => {
    describe('initial state', () => {
        it.each([
            ['phase', 'idle'],
            ['result', null],
            ['error', null],
            ['isExecuting', false],
        ] as const)('%s is %j', (key, expected) => {
            const s = createState();
            expect(s[key]).toBe(expected);
        });
    });

    describe('execute → stream result_stored', () => {
        it('yields result from SSE stream', async () => {
            const result = fakeExecutionResult();
            mockStarted();

            mockSseEvents(
                event({ event_type: 'status', status: 'running' }),
                event({ event_type: 'result_stored', result }),
            );

            const s = createState();
            await s.execute('print("hi")', 'python', '3.12');

            expect(s.result).toEqual(result);
            expect(s.phase).toBe('idle');
            expect(s.error).toBeNull();
        });

        it('sets result to null and no error when result_stored has no result', async () => {
            mockStarted();

            mockSseEvents(event({ event_type: 'result_stored' }));

            const s = createState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toBeNull();
            expect(s.error).toBeNull();
            expect(s.phase).toBe('idle');
        });
    });

    describe('execute → terminal failure sets error', () => {
        it.each([
            ['execution_failed', 'Execution failed.'],
            ['execution_timeout', 'Execution timed out.'],
            ['result_failed', 'Failed to store execution results.'],
        ] as const)('sets error on %s event', async (eventType, expectedError) => {
            mockStarted();

            mockSseEvents(event({ event_type: eventType }));

            const s = createState();
            await s.execute('x', 'python', '3.12');

            expect(s.error).toBe(expectedError);
            expect(s.phase).toBe('idle');
        });

        it('uses result from terminal failure event when available', async () => {
            const result = fakeExecutionResult();
            mockStarted();

            mockSseEvents(event({ event_type: 'execution_failed', result }));

            const s = createState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toEqual(result);
            expect(s.error).toBe('Execution failed.');
        });
    });

    describe('execute → stream ends without terminal event', () => {
        it('sets connection lost error and logs which execution lost its stream', async () => {
            const records = captureLogs();
            mockStarted();

            mockSseEvents(event({ event_type: 'status', status: 'running' }));

            const s = createState();
            await s.execute('x', 'python', '3.12');

            expect(s.error).toBe('Connection to server lost.');
            expect(s.result).toBeNull();
            expect(records).toEqual([
                expect.objectContaining({
                    level: 'warning',
                    category: ['integr8scode', 'editor'],
                    message: ['Event stream for execution ', 'exec-1', ' ended before its result'],
                }),
            ]);
        });

        it('logs each lost connection while the stream retries', async () => {
            const records = captureLogs();
            mockStarted();
            mockSseEvents(event({ event_type: 'result_stored', result: fakeExecutionResult() }));
            const s = createState();
            await s.execute('x', 'python', '3.12');
            const error = new TypeError('Failed to fetch');

            mockSseFn.mock.calls[0]![0]!.onSseError!(error);

            expect(records).toEqual([
                expect.objectContaining({
                    level: 'warning',
                    message: ['Event stream for execution ', 'exec-1', ' lost its connection: ', error, ''],
                }),
            ]);
        });
    });

    describe('execute → API error', () => {
        it('shows the API error when the execution fails to start, and opens no stream', async () => {
            mockApi(createExecutionApiV1ExecutePost).err({ status: 429, detail: 'rate limited' });

            const s = createState();
            await s.execute('x', 'python', '3.12');

            await vi.waitFor(() => expect(s.error).toBe('rate limited'));
            expect(s.phase).toBe('idle');
            expect(mockSseFn).not.toHaveBeenCalled();
        });

        it('is "starting" while the request is in flight', async () => {
            mockApi(createExecutionApiV1ExecutePost).mock.mockImplementation(() => new Promise(() => {}));

            const s = createState();
            void s.execute('x', 'python', '3.12');

            await vi.waitFor(() => expect(s.phase).toBe('starting'));
            expect(s.isExecuting).toBe(true);
        });
    });

    describe('abort', () => {
        it('resets phase to idle', () => {
            const s = createState();
            s.abort();
            expect(s.phase).toBe('idle');
        });
    });

    describe('reset', () => {
        it('clears all state', async () => {
            mockApi(createExecutionApiV1ExecutePost).err({ status: 500, detail: 'fail' });

            const s = createState();
            await s.execute('x', 'python', '3.12');
            await vi.waitFor(() => expect(s.error).toBe('fail'));

            s.reset();
            expect(s.phase).toBe('idle');
            expect(s.result).toBeNull();
            await vi.waitFor(() => expect(s.error).toBeNull());
        });
    });

    describe('malformed SSE data', () => {
        it('skips non-object events and continues', async () => {
            const result = fakeExecutionResult();
            mockStarted();

            // The generated client yields the raw text when an event isn't JSON
            const broken = '{broken' as unknown as SseExecutionEventSchema;
            mockSseEvents(broken, event({ event_type: 'result_stored', result }));

            const s = createState();
            await s.execute('x', 'python', '3.12');

            expect(s.result).toEqual(result);
        });
    });
});
