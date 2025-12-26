import {
    createExecutionApiV1ExecutePost,
    getResultApiV1ResultExecutionIdGet,
    type ExecutionResult,
    type EventType,
} from '$lib/api';
import { getErrorMessage } from '$lib/api-interceptors';

export type ExecutionPhase = 'idle' | 'starting' | 'queued' | 'scheduled' | 'running';

// Valid phases that can come from backend status updates
const VALID_BACKEND_PHASES = new Set<string>(['queued', 'scheduled', 'running']);

function toExecutionPhase(status: string | undefined, fallback: ExecutionPhase): ExecutionPhase {
    return status && VALID_BACKEND_PHASES.has(status) ? status as ExecutionPhase : fallback;
}

// Failure event types that should trigger fallback fetch
const FAILURE_EVENTS = new Set<EventType>(['execution_failed', 'execution_timeout', 'result_failed']);

export function createExecutionState() {
    let phase = $state<ExecutionPhase>('idle');
    let result = $state<ExecutionResult | null>(null);
    let error = $state<string | null>(null);

    function reset() {
        phase = 'idle';
        result = null;
        error = null;
    }

    async function execute(script: string, lang: string, langVersion: string): Promise<void> {
        reset();
        phase = 'starting';
        let executionId: string | null = null;

        try {
            const { data, error: execError } = await createExecutionApiV1ExecutePost({
                body: { script, lang, lang_version: langVersion }
            });
            if (execError) throw execError;

            executionId = data.execution_id;
            phase = toExecutionPhase(data.status, 'queued');

            const finalResult = await new Promise<ExecutionResult>((resolve, reject) => {
                const eventSource = new EventSource(`/api/v1/events/executions/${executionId}`, {
                    withCredentials: true
                });

                const fetchFallback = async () => {
                    try {
                        const { data, error } = await getResultApiV1ResultExecutionIdGet({
                            path: { execution_id: executionId! }
                        });
                        if (error) throw error;
                        resolve(data!);
                    } catch (e) {
                        reject(e);
                    }
                };

                eventSource.onmessage = async (event) => {
                    try {
                        const eventData = JSON.parse(event.data);
                        const eventType = eventData?.event_type || eventData?.type;

                        if (eventType === 'heartbeat' || eventType === 'connected') return;

                        if (eventData.status) {
                            phase = toExecutionPhase(eventData.status, phase);
                        }

                        if (eventType === 'result_stored' && eventData.result) {
                            eventSource.close();
                            resolve(eventData.result);
                            return;
                        }

                        if (FAILURE_EVENTS.has(eventType)) {
                            eventSource.close();
                            await fetchFallback();
                        }
                    } catch (err) {
                        console.error('SSE parse error:', err);
                    }
                };

                eventSource.onerror = async () => {
                    eventSource.close();
                    await fetchFallback();
                };
            });

            result = finalResult;
        } catch (err) {
            error = getErrorMessage(err, 'Error executing script.');
            if (executionId) {
                try {
                    const { data } = await getResultApiV1ResultExecutionIdGet({
                        path: { execution_id: executionId }
                    });
                    if (data) {
                        result = data;
                        error = null;
                    }
                } catch { /* keep error */ }
            }
        } finally {
            phase = 'idle';
        }
    }

    return {
        get phase() { return phase; },
        get result() { return result; },
        get error() { return error; },
        get isExecuting() { return phase !== 'idle'; },
        execute,
        reset
    };
}

export type ExecutionState = ReturnType<typeof createExecutionState>;
