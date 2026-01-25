import {
    createExecutionApiV1ExecutePost,
    getResultApiV1ResultExecutionIdGet,
    type ExecutionResult,
    type EventType,
} from '$lib/api';
import { getErrorMessage } from '$lib/api-interceptors';

export type ExecutionPhase = 'idle' | 'starting' | 'queued' | 'scheduled' | 'running';

const VALID_PHASES = new Set(['queued', 'scheduled', 'running']);
const TERMINAL_FAILURES: Set<EventType> = new Set(['execution_failed', 'execution_timeout', 'result_failed']);

export function createExecutionState() {
    let phase = $state<ExecutionPhase>('idle');
    let result = $state<ExecutionResult | null>(null);
    let error = $state<string | null>(null);
    let abortController: AbortController | null = null;

    function reset() {
        phase = 'idle';
        result = null;
        error = null;
    }

    function abort() {
        abortController?.abort();
        abortController = null;
        phase = 'idle';
    }

    async function execute(script: string, lang: string, langVersion: string): Promise<void> {
        abort();
        reset();
        phase = 'starting';

        try {
            const { data, error: execError } = await createExecutionApiV1ExecutePost({
                body: { script, lang, lang_version: langVersion }
            });
            if (execError) throw execError;

            const executionId = data.execution_id;
            phase = VALID_PHASES.has(data.status) ? data.status as ExecutionPhase : 'queued';

            result = await streamResult(executionId);
        } catch (err) {
            error = getErrorMessage(err, 'Error executing script.');
        } finally {
            abortController = null;
            phase = 'idle';
        }
    }

    async function streamResult(executionId: string): Promise<ExecutionResult> {
        abortController = new AbortController();

        const response = await fetch(`/api/v1/events/executions/${executionId}`, {
            headers: { 'Accept': 'text/event-stream' },
            credentials: 'include',
            signal: abortController.signal,
        });

        if (!response.ok) {
            if (response.status === 401) throw new Error('Unauthorized');
            return fetchResult(executionId);
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() ?? '';

                for (const line of lines) {
                    if (!line.startsWith('data:')) continue;

                    const eventData = JSON.parse(line.slice(5).trim());
                    const eventType = eventData?.event_type;

                    // Update phase from status events
                    if (eventData.status && VALID_PHASES.has(eventData.status)) {
                        phase = eventData.status as ExecutionPhase;
                    }

                    // Terminal: result received
                    if (eventType === 'result_stored' && eventData.result) {
                        return eventData.result;
                    }

                    // Terminal: failure - fetch result (may have partial output)
                    if (TERMINAL_FAILURES.has(eventType)) {
                        return fetchResult(executionId);
                    }
                }
            }
        } finally {
            reader.releaseLock();
        }

        // Stream ended without terminal event - fetch result
        return fetchResult(executionId);
    }

    async function fetchResult(executionId: string): Promise<ExecutionResult> {
        const { data, error } = await getResultApiV1ResultExecutionIdGet({
            path: { execution_id: executionId }
        });
        if (error) throw error;
        return data!;
    }

    return {
        get phase() { return phase; },
        get result() { return result; },
        get error() { return error; },
        get isExecuting() { return phase !== 'idle'; },
        execute,
        abort,
        reset
    };
}

export type ExecutionState = ReturnType<typeof createExecutionState>;
