<script lang="ts">
    import { Check, X, Undo2 } from '@lucide/svelte';
    import type { SagaStatusResponse } from '../../../lib/api';
    import { formatTimestamp, formatDurationBetween } from '../../../lib/formatters';
    import { getSagaStateInfo, EXECUTION_SAGA_STEPS } from '../../../lib/admin/sagas';
    import Modal from '../../Modal.svelte';

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

                {#if saga.saga_name === 'execution_saga'}
                    <div class="mb-4 p-4 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg overflow-x-auto">
                        <div class="flex items-start justify-between gap-0 min-w-[600px] pb-2">
                            {#each EXECUTION_SAGA_STEPS as step, index}
                                {@const isCompleted = saga.completed_steps.includes(step.name)}
                                {@const isCompensated = step.compensation && saga.compensated_steps.includes(step.compensation)}
                                {@const isCurrent = saga.current_step === step.name}
                                {@const isFailed = saga.state === 'failed' && isCurrent}

                                <div class="flex flex-col items-center flex-1 relative">
                                    <div class="flex items-center w-full relative h-12">
                                        <div class="flex-1 flex items-center justify-end">
                                            {#if index > 0}
                                                {@const prevCompleted = saga.completed_steps.includes(EXECUTION_SAGA_STEPS[index - 1].name)}
                                                <div class="h-0.5 w-full {prevCompleted && (isCompleted || isCompensated) ? 'bg-green-400' : 'bg-neutral-300 dark:bg-neutral-600'}"></div>
                                            {/if}
                                        </div>
                                        <div class="relative z-10 mx-1">
                                            <div class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold border-2
                                                {isCompleted ? 'bg-green-100 text-green-600 border-green-300 dark:bg-green-900/30 dark:border-green-600' :
                                                 isCompensated ? 'bg-yellow-100 text-yellow-600 border-yellow-300' :
                                                 isCurrent ? 'bg-blue-100 text-blue-600 border-blue-300 animate-pulse' :
                                                 isFailed ? 'bg-red-100 text-red-600 border-red-300' :
                                                 'bg-neutral-100 text-neutral-400 border-neutral-300 dark:bg-neutral-800'}">
                                                {#if isCompleted}<Check class="w-5 h-5" />
                                                {:else if isCompensated}<Undo2 class="w-4 h-4" />
                                                {:else if isCurrent}<div class="w-2 h-2 bg-current rounded-full"></div>
                                                {:else if isFailed}<X class="w-5 h-5" />
                                                {:else}<span class="text-sm font-bold">{index + 1}</span>{/if}
                                            </div>
                                        </div>
                                        <div class="flex-1 flex items-center justify-start">
                                            {#if index < EXECUTION_SAGA_STEPS.length - 1}
                                                {@const nextCompleted = saga.completed_steps.includes(EXECUTION_SAGA_STEPS[index + 1].name)}
                                                <div class="h-0.5 w-full {isCompleted && nextCompleted ? 'bg-green-400' : 'bg-neutral-300 dark:bg-neutral-600'}"></div>
                                            {/if}
                                        </div>
                                    </div>
                                    <div class="mt-2 text-xs font-medium text-center px-1">
                                        {step.label}
                                        {#if step.compensation && isCompensated}
                                            <div class="text-xs text-yellow-600 mt-1">(compensated)</div>
                                        {/if}
                                    </div>
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}

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

            {#if saga.context_data && Object.keys(saga.context_data).length > 0}
                <div class="mt-6">
                    <h3 class="font-semibold mb-3">Context Data</h3>
                    <div class="p-4 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
                        <pre class="text-sm overflow-x-auto">{JSON.stringify(saga.context_data, null, 2)}</pre>
                    </div>
                </div>
            {/if}
        {/if}
    {/snippet}
</Modal>
