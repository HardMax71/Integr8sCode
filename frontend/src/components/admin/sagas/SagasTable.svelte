<script lang="ts">
    import type { SagaStatusResponse } from '$lib/api';
    import { formatTimestamp, formatDurationBetween } from '$lib/formatters';
    import { getSagaStateInfo } from '$lib/admin/sagas';
    import Spinner from '$components/Spinner.svelte';

    interface Props {
        sagas: SagaStatusResponse[];
        loading: boolean;
        onViewDetails: (sagaId: string) => void;
        onViewExecution: (executionId: string) => void;
    }

    let { sagas, loading, onViewDetails, onViewExecution }: Props = $props();
</script>

<div class="bg-bg-default dark:bg-dark-bg-default rounded-lg shadow overflow-hidden">
    {#if loading && sagas.length === 0}
        <div class="p-8 text-center">
            <Spinner size="xlarge" className="mx-auto mb-4" />
            <p class="text-fg-muted">Loading sagas...</p>
        </div>
    {:else if sagas.length === 0}
        <div class="p-8 text-center text-fg-muted">No sagas found</div>
    {:else}
        <!-- Mobile Card View -->
        <div class="block lg:hidden">
            {#each sagas as saga}
                {@const stateInfo = getSagaStateInfo(saga.state)}
                <div class="p-4 border-b border-border-default dark:border-dark-border-default hover:bg-bg-alt">
                    <div class="flex justify-between items-start mb-2">
                        <div class="flex-1 min-w-0 mr-2">
                            <div class="font-medium text-sm">{saga.saga_name}</div>
                            <div class="text-xs text-fg-muted mt-1">ID: {saga.saga_id.slice(0, 12)}...</div>
                        </div>
                        <span class="badge {stateInfo.color}">
                            {stateInfo.label}
                            {#if saga.retry_count > 0}<span class="ml-1">({saga.retry_count})</span>{/if}
                        </span>
                    </div>
                    <div class="grid grid-cols-2 gap-2 text-xs mb-2">
                        <div>
                            <span class="text-fg-muted">Started:</span>
                            <div>{formatTimestamp(saga.created_at)}</div>
                        </div>
                        <div>
                            <span class="text-fg-muted">Duration:</span>
                            <div>{formatDurationBetween(saga.created_at, saga.completed_at || saga.updated_at)}</div>
                        </div>
                    </div>
                    <div class="mb-2 text-xs text-fg-muted">
                        Steps completed: {saga.completed_steps.length}
                        {#if saga.current_step}
                            <span class="ml-2 text-blue-500">▶ {saga.current_step}</span>
                        {/if}
                    </div>
                    <div class="flex gap-2">
                        <button
                            onclick={() => onViewExecution(saga.execution_id)}
                            class="flex-1 btn btn-sm btn-secondary-outline"
                        >
                            Execution
                        </button>
                        <button
                            onclick={() => onViewDetails(saga.saga_id)}
                            class="flex-1 btn btn-sm btn-primary"
                        >
                            View Details
                        </button>
                    </div>
                </div>
            {/each}
        </div>

        <!-- Desktop Table View -->
        <div class="hidden lg:block overflow-x-auto">
            <table class="table">
                <thead class="table-header">
                    <tr>
                        <th class="table-header-cell">Saga</th>
                        <th class="table-header-cell">State</th>
                        <th class="table-header-cell">Progress</th>
                        <th class="table-header-cell">Started</th>
                        <th class="table-header-cell">Duration</th>
                        <th class="table-header-cell text-center">Actions</th>
                    </tr>
                </thead>
                <tbody class="table-body">
                    {#each sagas as saga}
                        {@const stateInfo = getSagaStateInfo(saga.state)}
                        <tr class="table-row">
                            <td class="table-cell">
                                <div class="font-medium">{saga.saga_name}</div>
                                <div class="text-sm text-fg-muted">ID: {saga.saga_id.slice(0, 8)}...</div>
                                <button
                                    onclick={() => onViewExecution(saga.execution_id)}
                                    class="text-xs text-primary hover:text-primary-dark"
                                >
                                    Execution: {saga.execution_id.slice(0, 8)}...
                                </button>
                            </td>
                            <td class="table-cell">
                                <span class="badge {stateInfo.color}">{stateInfo.label}</span>
                                {#if saga.retry_count > 0}
                                    <span class="ml-2 text-xs text-fg-muted">(Retry: {saga.retry_count})</span>
                                {/if}
                            </td>
                            <td class="table-cell">
                                <div class="text-sm">
                                    <span class="text-fg-muted">{saga.completed_steps.length} steps</span>
                                    {#if saga.current_step}
                                        <div class="text-xs text-fg-muted mt-1 truncate">Current: {saga.current_step}</div>
                                    {/if}
                                </div>
                            </td>
                            <td class="table-cell text-sm">{formatTimestamp(saga.created_at)}</td>
                            <td class="table-cell text-sm">
                                {formatDurationBetween(saga.created_at, saga.completed_at || saga.updated_at)}
                            </td>
                            <td class="table-cell text-center">
                                <button
                                    onclick={() => onViewDetails(saga.saga_id)}
                                    class="text-primary hover:text-primary-dark"
                                >
                                    View Details
                                </button>
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</div>
