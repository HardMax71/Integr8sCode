<script lang="ts">
    import { X } from '@lucide/svelte';
    import type { EventReplayStatusResponse } from '../../../lib/api';

    interface Props {
        session: EventReplayStatusResponse | null;
        onClose: () => void;
    }

    let { session, onClose }: Props = $props();
</script>

{#if session}
    <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6 relative">
        <!-- Close button -->
        <button
            onclick={onClose}
            class="absolute top-2 right-2 p-1 hover:bg-blue-100 dark:hover:bg-blue-800 rounded-lg transition-colors"
            title="Close"
        >
            <X size={20} class="text-blue-600 dark:text-blue-400" />
        </button>

        <div class="flex items-center justify-between mb-2 pr-8">
            <h3 class="font-semibold text-blue-900 dark:text-blue-100">Replay in Progress</h3>
            <span class="text-sm text-blue-700 dark:text-blue-300">
                {session.status}
            </span>
        </div>
        <div class="mb-2">
            <div class="flex justify-between text-sm text-blue-700 dark:text-blue-300 mb-1">
                <span>Progress: {session.replayed_events} / {session.total_events} events</span>
                <span>{session.progress_percentage}%</span>
            </div>
            <div class="w-full bg-blue-200 dark:bg-blue-800 rounded-full h-2">
                <div
                    class="bg-blue-600 dark:bg-blue-400 h-2 rounded-full transition-all duration-300"
                    style="width: {session.progress_percentage}%"
                ></div>
            </div>
        </div>

        {#if session.failed_events > 0}
            <div class="mt-2">
                <div class="text-sm text-red-600 dark:text-red-400">
                    Failed: {session.failed_events} events
                </div>
                {#if session.error_message}
                    <div class="mt-1 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded">
                        <p class="text-xs text-red-700 dark:text-red-300 font-mono">
                            Error: {session.error_message}
                        </p>
                    </div>
                {/if}
                {#if session.failed_event_errors && session.failed_event_errors.length > 0}
                    <div class="mt-2 space-y-1">
                        {#each session.failed_event_errors as error}
                            <div class="p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-xs">
                                <div class="font-mono text-neutral-600 dark:text-neutral-400">{error.event_id}</div>
                                <div class="text-red-700 dark:text-red-300 mt-1">{error.error}</div>
                            </div>
                        {/each}
                    </div>
                {/if}
            </div>
        {/if}

        {#if session.execution_results && session.execution_results.length > 0}
            <div class="mt-4 border-t border-blue-200 dark:border-blue-800 pt-3">
                <h4 class="text-sm font-semibold text-blue-900 dark:text-blue-100 mb-2">Execution Results:</h4>
                <div class="space-y-2">
                    {#each session.execution_results as result}
                        <div class="bg-surface-overlay dark:bg-dark-surface-overlay rounded p-2 text-sm">
                            <div class="flex justify-between items-start">
                                <div>
                                    <span class="font-mono text-xs text-neutral-500">{result.execution_id}</span>
                                    <div class="flex items-center gap-2 mt-1">
                                        <span class="px-2 py-0.5 rounded text-xs {
                                            result.status === 'completed' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' :
                                            result.status === 'failed' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' :
                                            'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
                                        }">
                                            {result.status}
                                        </span>
                                        {#if result.execution_time}
                                            <span class="text-neutral-500 dark:text-neutral-400">
                                                {result.execution_time.toFixed(2)}s
                                            </span>
                                        {/if}
                                    </div>
                                </div>
                                {#if result.output || result.errors}
                                    <div class="text-right">
                                        {#if result.output}
                                            <div class="font-mono text-green-600 dark:text-green-400">
                                                Output: {result.output}
                                            </div>
                                        {/if}
                                        {#if result.errors}
                                            <div class="font-mono text-red-600 dark:text-red-400">
                                                Error: {result.errors}
                                            </div>
                                        {/if}
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
