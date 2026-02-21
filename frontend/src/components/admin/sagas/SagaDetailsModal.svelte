<script lang="ts">
    import { Check, X, Undo2 } from '@lucide/svelte';
    import type { SagaStatusResponse } from '$lib/api';
    import { formatTimestamp, formatDurationBetween } from '$lib/formatters';
    import { getSagaStateInfo } from '$lib/admin/sagas';
    import Modal from '$components/Modal.svelte';

    interface Props {
        saga: SagaStatusResponse | null;
        open: boolean;
        onClose: () => void;
        onViewExecution?: (executionId: string) => void;
    }

    let { saga, open, onClose, onViewExecution }: Props = $props();

    function handleViewExecution(): void {
        if (saga) {
            onClose();
            onViewExecution?.(saga.execution_id);
        }
    }
</script>

<Modal {open} title="Saga Details" {onClose} size="lg">
    {#snippet children()}
        {#if saga}
            {@const stateInfo = getSagaStateInfo(saga.state)}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
                <div>
                    <h3 class="font-semibold mb-3">Basic Information</h3>
                    <dl class="space-y-2 text-sm">
                        <div>
                            <dt class="text-fg-muted">Saga ID</dt>
                            <dd class="font-mono">{saga.saga_id}</dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">Saga Name</dt>
                            <dd class="font-medium">{saga.saga_name}</dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">Execution ID</dt>
                            <dd>
                                <button
                                    onclick={handleViewExecution}
                                    class="text-primary hover:text-primary-dark font-mono"
                                >
                                    {saga.execution_id}
                                </button>
                            </dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">State</dt>
                            <dd><span class="badge {stateInfo.color}">{stateInfo.label}</span></dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">Retry Count</dt>
                            <dd>{saga.retry_count}</dd>
                        </div>
                    </dl>
                </div>
                <div>
                    <h3 class="font-semibold mb-3">Timing Information</h3>
                    <dl class="space-y-2 text-sm">
                        <div>
                            <dt class="text-fg-muted">Created At</dt>
                            <dd>{formatTimestamp(saga.created_at)}</dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">Updated At</dt>
                            <dd>{formatTimestamp(saga.updated_at)}</dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">Completed At</dt>
                            <dd>{formatTimestamp(saga.completed_at)}</dd>
                        </div>
                        <div>
                            <dt class="text-fg-muted">Duration</dt>
                            <dd>{formatDurationBetween(saga.created_at, saga.completed_at || saga.updated_at)}</dd>
                        </div>
                    </dl>
                </div>
            </div>

            <div class="mt-6">
                <h3 class="font-semibold mb-3">Execution Steps</h3>

                {#if saga.current_step}
                    <div class="mb-4 p-3 alert alert-info">
                        <span class="font-medium">Current Step:</span> {saga.current_step}
                    </div>
                {/if}

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                        <h4 class="text-sm font-medium mb-2 text-green-600">Completed ({saga.completed_steps.length})</h4>
                        {#if saga.completed_steps.length > 0}
                            <ul class="space-y-1">
                                {#each saga.completed_steps as step}
                                    <li class="flex items-center gap-2 text-sm">
                                        <Check class="w-4 h-4 text-green-500" />{step}
                                    </li>
                                {/each}
                            </ul>
                        {:else}
                            <p class="text-sm text-fg-muted">No completed steps</p>
                        {/if}
                    </div>
                    <div>
                        <h4 class="text-sm font-medium mb-2 text-yellow-600">Compensated ({saga.compensated_steps.length})</h4>
                        {#if saga.compensated_steps.length > 0}
                            <ul class="space-y-1">
                                {#each saga.compensated_steps as step}
                                    <li class="flex items-center gap-2 text-sm">
                                        <Undo2 class="w-4 h-4 text-yellow-500" />{step}
                                    </li>
                                {/each}
                            </ul>
                        {:else}
                            <p class="text-sm text-fg-muted">No compensated steps</p>
                        {/if}
                    </div>
                </div>
            </div>

            {#if saga.error_message}
                <div class="mt-6">
                    <h3 class="font-semibold mb-3 text-red-600">Error Information</h3>
                    <div class="p-4 alert alert-danger">
                        <pre class="text-sm whitespace-pre-wrap">{saga.error_message}</pre>
                    </div>
                </div>
            {/if}

        {/if}
    {/snippet}
</Modal>
