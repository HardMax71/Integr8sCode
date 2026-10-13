<script lang="ts">
    import { renderSnippet, type PaginationState } from '@tanstack/svelte-table';
    import type { SagaStatusResponse } from '#lib/api/index.ts';
    import { fieldTitle, formatTimestamp, formatDurationBetween } from '#lib/formatters.ts';
    import { getSagaStateInfo } from '#lib/admin/sagas/index.ts';
    import { columnHelper, createServerTable } from '#lib/data-table.ts';
    import DataTable from '#components/DataTable.svelte';
    import Pagination from '#components/Pagination.svelte';

    interface Props {
        sagas: SagaStatusResponse[];
        rowCount: number;
        pagination: PaginationState;
        loading: boolean;
        onViewDetails: (sagaId: string) => void;
        onViewExecution: (executionId: string) => void;
    }

    let { sagas, rowCount, pagination = $bindable(), loading, onViewDetails, onViewExecution }: Props = $props();

    const column = columnHelper<SagaStatusResponse>();
    const columns = [
        column.accessor('saga_name', { cell: ({ row }) => renderSnippet(sagaCell, row.original) }),
        column.accessor('state', { cell: ({ row }) => renderSnippet(stateCell, row.original) }),
        column.display({ id: 'progress', cell: ({ row }) => renderSnippet(progressCell, row.original) }),
        column.accessor('created_at', { cell: ({ getValue }) => formatTimestamp(getValue()) }),
        column.display({
            id: 'duration',
            cell: ({ row }) =>
                formatDurationBetween(row.original.created_at, row.original.completed_at || row.original.updated_at),
        }),
        column.display({
            id: 'actions',
            meta: { class: 'text-center' },
            cell: ({ row }) => renderSnippet(actionsCell, row.original),
        }),
    ];

    const table = createServerTable(columns, {
        get rows() {
            return sagas;
        },
        get rowCount() {
            return rowCount;
        },
        get pagination() {
            return pagination;
        },
        set pagination(next) {
            pagination = next;
        },
    });
</script>

{#snippet sagaCell(saga: SagaStatusResponse)}
    <div class="font-medium">{saga.saga_name}</div>
    <div class="text-sm text-fg-muted">{fieldTitle('saga_id')} {saga.saga_id.slice(0, 8)}...</div>
    <button
        type="button"
        onclick={() => onViewExecution(saga.execution_id)}
        class="text-xs text-accent hover:text-accent"
    >
        {fieldTitle('execution_id')}
        {saga.execution_id.slice(0, 8)}...
    </button>
{/snippet}

{#snippet stateCell(saga: SagaStatusResponse)}
    {@const stateInfo = getSagaStateInfo(saga.state)}
    <span class="badge {stateInfo.color}">{saga.state}</span>
    {#if saga.retry_count > 0}
        <span class="ml-2 text-xs text-fg-muted">({fieldTitle('retry_count')} {saga.retry_count})</span>
    {/if}
{/snippet}

{#snippet progressCell(saga: SagaStatusResponse)}
    <div class="text-sm">
        <span class="text-fg-muted">{fieldTitle('completed_steps')} {saga.completed_steps.length}</span>
        {#if saga.current_step}
            <div class="text-xs text-fg-muted mt-1 truncate">{fieldTitle('current_step')} {saga.current_step}</div>
        {/if}
    </div>
{/snippet}

{#snippet actionsCell(saga: SagaStatusResponse)}
    <button type="button" onclick={() => onViewDetails(saga.saga_id)} class="text-accent hover:text-accent">
        View Details
    </button>
{/snippet}

<div class="bg-page rounded-lg shadow overflow-hidden">
    <DataTable {table} label="Sagas" {loading} emptyText="No sagas found" />
    {#if rowCount > 0}
        <div class="p-4 border-t divider">
            <Pagination {table} itemName="sagas" />
        </div>
    {/if}
</div>
