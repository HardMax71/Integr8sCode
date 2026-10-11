import { createMutation } from '@tanstack/svelte-query';
import {
    createExecutionApiV1ExecutePostMutation,
    executionEventsApiV1EventsExecutionsExecutionIdGet,
    type ExecutionResponse,
    type ExecutionResult,
    type ExecutionStatus,
    type EventType,
    type SseControlEvent,
} from '#lib/api/index.ts';
import { getErrorMessage } from '#lib/api-interceptors.ts';

export type ExecutionPhase = 'idle' | 'starting' | 'queued' | 'scheduled' | 'running';

function isActivePhase(s: ExecutionStatus): s is 'queued' | 'scheduled' | 'running' {
    return s === 'queued' || s === 'scheduled' || s === 'running';
}

function isTerminalFailure(e: EventType | SseControlEvent): boolean {
    return e === 'execution_failed' || e === 'execution_timeout' || e === 'result_failed';
}

class ExecutionState {
    #phase = $state<Exclude<ExecutionPhase, 'starting'>>('idle');
    result = $state<ExecutionResult | null>(null);
    #streamError = $state<string | null>(null);
    #controller: AbortController | null = null;
    #start = createMutation(() => createExecutionApiV1ExecutePostMutation());

    get phase(): ExecutionPhase {
        return this.#start.isPending ? 'starting' : this.#phase;
    }

    get error(): string | null {
        if (this.#streamError) return this.#streamError;
        return this.#start.error ? getErrorMessage(this.#start.error, 'Failed to start execution.') : null;
    }

    get isExecuting() {
        return this.phase !== 'idle';
    }

    reset() {
        this.#phase = 'idle';
        this.result = null;
        this.#streamError = null;
        this.#start.reset();
    }

    abort() {
        this.#controller?.abort();
        this.#controller = null;
        this.#phase = 'idle';
    }

    async execute(script: string, lang: string, langVersion: string): Promise<void> {
        this.abort();
        this.reset();

        // A failed start shows through this.error, and the query client has already toasted it
        const started = await this.#start
            .mutateAsync({ body: { script, lang, lang_version: langVersion } })
            .catch(() => null);
        if (started) await this.#follow(started);
    }

    async #follow(data: ExecutionResponse): Promise<void> {
        const controller = new AbortController();
        this.#controller = controller;
        this.#phase = isActivePhase(data.status) ? data.status : 'queued';

        const { stream } = await executionEventsApiV1EventsExecutionsExecutionIdGet({
            path: { execution_id: data.execution_id },
            signal: controller.signal,
            sseMaxRetryAttempts: 3,
        });

        let terminalReceived = false;
        for await (const ev of stream) {
            if (ev.status && isActivePhase(ev.status)) {
                this.#phase = ev.status;
            }

            if (ev.event_type === 'result_stored') {
                this.result = ev.result;
                terminalReceived = true;
                break;
            }

            if (isTerminalFailure(ev.event_type)) {
                this.result = ev.result;
                this.#streamError =
                    ev.event_type === 'execution_timeout'
                        ? 'Execution timed out.'
                        : ev.event_type === 'result_failed'
                          ? 'Failed to store execution results.'
                          : 'Execution failed.';
                terminalReceived = true;
                break;
            }
        }

        if (!terminalReceived && !controller.signal.aborted) {
            this.#streamError = 'Connection to server lost.';
        }
        this.#controller = null;
        this.#phase = 'idle';
    }
}

export function createExecutionState() {
    return new ExecutionState();
}

export type { ExecutionState };
