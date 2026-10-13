<script lang="ts">
    import { X } from '@lucide/svelte';
    import { toast } from 'svelte-sonner';
    import {
        ReplayStatus,
        streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
        type EventReplayStatusResponse,
    } from '#lib/api/index.ts';
    import { getLogger } from '@logtape/logtape';
    import { fieldTitle } from '#lib/formatters.ts';
    import { EXECUTION_STATUS_BADGE } from '#lib/badges.ts';

    interface Props {
        sessionId: string;
        onClose: () => void;
    }

    let { sessionId, onClose }: Props = $props();

    const log = getLogger(['integr8scode', 'replay']);
    let session = $state<EventReplayStatusResponse | null>(null);

    // Follows the session while the banner is open; closing it aborts the stream
    $effect(() => {
        const controller = new AbortController();
        follow(sessionId, controller.signal).catch((err: unknown) => {
            if (!controller.signal.aborted)
                log.error('Status stream for replay {sessionId} stopped: {error}', { sessionId, error: err });
        });
        return () => controller.abort();
    });

    async function follow(id: string, signal: AbortSignal): Promise<void> {
        const { stream } = await streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet({
            path: { session_id: id },
            signal,
            onSseError: (error) => {
                if (!signal.aborted)
                    log.warning('Status stream for replay {sessionId} lost its connection: {error}', {
                        sessionId: id,
                        error,
                    });
            },
            sseMaxRetryAttempts: 3,
        });
        // The server sends the whole session first and on every change, and closes the stream once it ends
        for await (const status of stream) {
            session = status;
            if (status.status === ReplayStatus.COMPLETED) {
                toast.success(`Replay completed! Processed ${status.replayed_events} events successfully.`);
            } else if (status.status === ReplayStatus.FAILED) {
                toast.error(`Replay failed: ${status.errors?.[0]?.error || 'Unknown error'}`);
            }
        }
    }
</script>

{#if session}
    <div class="bg-info-soft border border-info/30 rounded-lg p-4 mb-6 relative">
        <!-- Close button -->
        <button
            type="button"
            onclick={onClose}
            class="absolute top-2 right-2 p-1 hover:bg-info-soft rounded-lg transition-colors"
            title="Close"
        >
            <X size={20} class="text-info" />
        </button>

        <div class="flex items-center justify-between mb-2 pr-8">
            <h3 class="font-semibold text-info">Replay in Progress</h3>
            <span class="text-sm text-info">
                {session.status}
            </span>
        </div>
        <div class="mb-2">
            <div class="flex justify-between text-sm text-info mb-1">
                <span>Progress: {session.replayed_events} / {session.total_events} events</span>
                <span>{session.progress_percentage}%</span>
            </div>
            <div class="w-full bg-info/25 rounded-full h-2 overflow-hidden">
                <div
                    class="bg-info h-2 rounded-full transition-all duration-300"
                    style="width: {Math.min(session.progress_percentage, 100)}%"
                ></div>
            </div>
        </div>

        {#if session.errors?.length}
            <div class="mt-2 space-y-1">
                {#each session.errors as err, i (i)}
                    <div class="p-2 bg-danger-soft border border-danger/30 rounded text-xs">
                        {#if err.event_id}<div class="font-mono text-fg-muted">
                                {err.event_id}
                            </div>{/if}
                        <div class="text-danger">{err.error}</div>
                    </div>
                {/each}
            </div>
        {/if}

        {#if session.execution_results?.length}
            <div class="mt-4 border-t border-info/30 pt-3">
                <h4 class="text-sm font-semibold text-info mb-2">
                    {fieldTitle('execution_results')}
                </h4>
                <div class="space-y-2">
                    {#each session.execution_results as result (result.execution_id)}
                        <div class="bg-surface rounded p-2 text-sm">
                            <div class="flex justify-between items-start">
                                <div>
                                    <span class="font-mono text-xs text-fg-muted">{result.execution_id}</span>
                                    <div class="flex items-center gap-2 mt-1">
                                        <span class="badge {EXECUTION_STATUS_BADGE[result.status]}">
                                            {result.status}
                                        </span>
                                        {#if result.resource_usage?.execution_time_wall_seconds}
                                            <span class="text-fg-muted"
                                                >{result.resource_usage.execution_time_wall_seconds.toFixed(2)}s</span
                                            >
                                        {/if}
                                    </div>
                                </div>
                                {#if result.stdout || result.stderr}
                                    <div class="text-right">
                                        {#if result.stdout}<div class="font-mono text-success">
                                                {result.stdout}
                                            </div>{/if}
                                        {#if result.stderr}<div class="font-mono text-danger">
                                                {result.stderr}
                                            </div>{/if}
                                    </div>
                                {/if}
                            </div>
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    </div>
{/if}
