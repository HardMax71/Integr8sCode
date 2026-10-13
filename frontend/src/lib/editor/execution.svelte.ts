import { createMutation } from '@tanstack/svelte-query';
import { Context } from 'runed';
import { getLogger } from '@logtape/logtape';
import {
    createExecutionApiV1ExecutePostMutation,
    executionEventsApiV1EventsExecutionsExecutionIdGet,
    EventType,
    ExecutionStatus,
    type ExecutionResponse,
    type ExecutionResult,
    type SseControlEvent,
} from '#lib/api/index.ts';

const log = getLogger(['integr8scode', 'editor']);

type ActiveStatus = Extract<ExecutionStatus, 'queued' | 'scheduled' | 'running'>;

export type ExecutionPhase = 'idle' | 'starting' | ActiveStatus;

const ACTIVE_STATUSES: readonly ExecutionStatus[] = [
    ExecutionStatus.QUEUED,
    ExecutionStatus.SCHEDULED,
    ExecutionStatus.RUNNING,
];

const FAILURE_EVENTS: readonly (EventType | SseControlEvent)[] = [
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
    EventType.RESULT_FAILED,
];

function isActivePhase(s: ExecutionStatus): s is ActiveStatus {
    return ACTIVE_STATUSES.includes(s);
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
        return this.#start.error?.detail ?? null;
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
        this.#phase = isActivePhase(data.status) ? data.status : ExecutionStatus.QUEUED;

        const { stream } = await executionEventsApiV1EventsExecutionsExecutionIdGet({
            path: { execution_id: data.execution_id },
            signal: controller.signal,
            onSseError: (error) => {
                if (!controller.signal.aborted)
                    log.warning('Event stream for execution {executionId} lost its connection: {error}', {
                        executionId: data.execution_id,
                        error,
                    });
            },
            sseMaxRetryAttempts: 3,
        });

        let terminalReceived = false;
        for await (const ev of stream) {
            if (ev.status && isActivePhase(ev.status)) {
                this.#phase = ev.status;
            }

            if (ev.event_type === EventType.RESULT_STORED) {
                this.result = ev.result;
                terminalReceived = true;
                break;
            }

            if (FAILURE_EVENTS.includes(ev.event_type)) {
                this.result = ev.result;
                this.#streamError =
                    ev.event_type === EventType.EXECUTION_TIMEOUT
                        ? 'Execution timed out.'
                        : ev.event_type === EventType.RESULT_FAILED
                          ? 'Failed to store execution results.'
                          : 'Execution failed.';
                terminalReceived = true;
                break;
            }
        }

        if (!terminalReceived && !controller.signal.aborted) {
            log.warning('Event stream for execution {executionId} ended before its result', {
                executionId: data.execution_id,
            });
            this.#streamError = 'Connection to server lost.';
        }
        this.#controller = null;
        this.#phase = 'idle';
    }
}

export function createExecutionState() {
    return new ExecutionState();
}

/** The page's execution, for the components that replace the script to clear its output */
export const executionContext = new Context<ExecutionState>('execution');

export type { ExecutionState };
