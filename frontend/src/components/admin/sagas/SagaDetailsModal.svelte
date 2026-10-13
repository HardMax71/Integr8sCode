<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { Check, Undo2 } from '@lucide/svelte';
    import { getSagaStatusApiV1SagasSagaIdGetOptions } from '#lib/api/index.ts';
    import { fieldTitle, formatTimestamp, formatDurationBetween } from '#lib/formatters.ts';
    import { getSagaStateInfo } from '#lib/admin/sagas/index.ts';
    import Modal from '#components/Modal.svelte';

    interface Props {
        sagaId: string;
        onClose: () => void;
        onViewExecution: (executionId: string) => void;
    }

    let { sagaId, onClose, onViewExecution }: Props = $props();

    const details = createQuery(() => getSagaStatusApiV1SagasSagaIdGetOptions({ path: { saga_id: sagaId } }));

    // A failed load already showed the interceptor's toast, so the modal closes instead of staying empty
    $effect(() => {
        if (details.isError) onClose();
    });
    const saga = $derived(details.data);

    // Closing clears the id the query reads, so take the execution id first
    function viewExecution(executionId: string): void {
        onClose();
        onViewExecution(executionId);
    }
</script>

<Modal open title="Saga Details" {onClose} size="lg">
    {#if saga}
        {@const stateInfo = getSagaStateInfo(saga.state)}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
            <div>
                <h3 class="font-semibold mb-3">Basic Information</h3>
                <dl class="space-y-2 text-sm">
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('saga_id')}</dt>
                        <dd class="font-mono">{saga.saga_id}</dd>
                    </div>
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('saga_name')}</dt>
                        <dd class="font-medium">{saga.saga_name}</dd>
                    </div>
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('execution_id')}</dt>
                        <dd>
                            <button
                                type="button"
                                onclick={() => viewExecution(saga.execution_id)}
                                class="text-accent hover:text-accent font-mono"
                            >
                                {saga.execution_id}
                            </button>
                        </dd>
                    </div>
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('state')}</dt>
                        <dd><span class="badge {stateInfo.color}">{saga.state}</span></dd>
                    </div>
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('retry_count')}</dt>
                        <dd>{saga.retry_count}</dd>
                    </div>
                </dl>
            </div>
            <div>
                <h3 class="font-semibold mb-3">Timing Information</h3>
                <dl class="space-y-2 text-sm">
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('created_at')}</dt>
                        <dd>{formatTimestamp(saga.created_at)}</dd>
                    </div>
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('updated_at')}</dt>
                        <dd>{formatTimestamp(saga.updated_at)}</dd>
                    </div>
                    <div>
                        <dt class="text-fg-muted">{fieldTitle('completed_at')}</dt>
                        <dd>{formatTimestamp(saga.completed_at)}</dd>
                    </div>
                </dl>
                <p class="mt-2 text-sm">
                    <span class="block text-fg-muted">Duration</span>
                    {formatDurationBetween(saga.created_at, saga.completed_at || saga.updated_at)}
                </p>
            </div>
        </div>

        <div class="mt-6">
            <h3 class="font-semibold mb-3">Execution Steps</h3>

            {#if saga.current_step}
                <dl class="mb-4 p-3 alert alert-info">
                    <dt class="font-medium">{fieldTitle('current_step')}</dt>
                    <dd>{saga.current_step}</dd>
                </dl>
            {/if}

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                    <h4 class="text-sm font-medium mb-2 text-success">
                        {fieldTitle('completed_steps')} ({saga.completed_steps.length})
                    </h4>
                    {#if saga.completed_steps.length > 0}
                        <ul class="space-y-1">
                            {#each saga.completed_steps as step (step)}
                                <li class="flex items-center gap-2 text-sm">
                                    <Check class="size-4 text-success" />{step}
                                </li>
                            {/each}
                        </ul>
                    {:else}
                        <p class="text-sm text-fg-muted">No completed steps</p>
                    {/if}
                </div>
                <div>
                    <h4 class="text-sm font-medium mb-2 text-warning">
                        {fieldTitle('compensated_steps')} ({saga.compensated_steps.length})
                    </h4>
                    {#if saga.compensated_steps.length > 0}
                        <ul class="space-y-1">
                            {#each saga.compensated_steps as step (step)}
                                <li class="flex items-center gap-2 text-sm">
                                    <Undo2 class="size-4 text-warning" />{step}
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
                <h3 class="font-semibold mb-3 text-danger">{fieldTitle('error_message')}</h3>
                <div class="p-4 alert alert-danger">
                    <pre class="text-sm whitespace-pre-wrap">{saga.error_message}</pre>
                </div>
            </div>
        {/if}
    {/if}
</Modal>
