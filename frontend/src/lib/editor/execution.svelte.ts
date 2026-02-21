import {
    createExecutionApiV1ExecutePost,
    executionEventsApiV1EventsExecutionsExecutionIdGet,
    type ExecutionResult,
    type ExecutionStatus,
    type EventType,
    type SseControlEvent,
} from '$lib/api';
import { getErrorMessage } from '$lib/api-interceptors';

export type ExecutionPhase = 'idle' | 'starting' | 'queued' | 'scheduled' | 'running';

function isActivePhase(s: ExecutionStatus): s is 'queued' | 'scheduled' | 'running' {
    return s === 'queued' || s === 'scheduled' || s === 'running';
}

function isTerminalFailure(e: EventType | SseControlEvent): boolean {
    return e === 'execution_failed' || e === 'execution_timeout' || e === 'result_failed';
}

class ExecutionState {
    phase = $state<ExecutionPhase>('idle');
    result = $state<ExecutionResult | null>(null);
    error = $state<string | null>(null);
    #controller: AbortController | null = null;

    get isExecuting() { return this.phase !== 'idle'; }

    reset() {
        this.phase = 'idle';
        this.result = null;
        this.error = null;
    }

    abort() {
        this.#controller?.abort();
        this.#controller = null;
        this.phase = 'idle';
    }

    async execute(script: string, lang: string, langVersion: string): Promise<void> {
        this.abort();
        this.reset();
        this.phase = 'starting';

        const { data, error } = await createExecutionApiV1ExecutePost({
            body: { script, lang, lang_version: langVersion },
        });
        if (error) {
            this.error = getErrorMessage(error, 'Failed to start execution.');
            this.phase = 'idle';
            return;
        }

        const controller = new AbortController();
        this.#controller = controller;
        this.phase = isActivePhase(data.status) ? data.status : 'queued';

        const { stream } = await executionEventsApiV1EventsExecutionsExecutionIdGet({
            path: { execution_id: data.execution_id },
            signal: controller.signal,
            sseMaxRetryAttempts: 3,
        });

        let terminalReceived = false;
        for await (const ev of stream) {
            if (ev.status && isActivePhase(ev.status)) {
                this.phase = ev.status;
            }

            if (ev.event_type === 'result_stored') {
                this.result = ev.result ?? null;
                terminalReceived = true;
                break;
            }

            if (isTerminalFailure(ev.event_type)) {
                this.result = ev.result ?? null;
                this.error = ev.message ?? 'Execution failed.';
                terminalReceived = true;
                break;
            }
        }

        if (!terminalReceived && !controller.signal.aborted) {
            this.error = 'Connection to server lost.';
        }
        this.#controller = null;
        this.phase = 'idle';
    }
}

export function createExecutionState() { return new ExecutionState(); }

export type { ExecutionState };
