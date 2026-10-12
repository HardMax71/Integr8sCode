<script lang="ts">
    import { renderSnippet, type PaginationState } from '@tanstack/svelte-table';
    import { QueuePriority, type AdminExecutionResponse, type ExecutionStatus } from '#lib/api/index.ts';
    import { formatTimestamp, truncate } from '#lib/formatters.ts';
    import { columnHelper, createServerTable } from '#lib/data-table.ts';
    import DataTable from '#components/DataTable.svelte';
    import Pagination from '#components/Pagination.svelte';

    interface Props {
        executions: AdminExecutionResponse[];
        rowCount: number;
        pagination: PaginationState;
        loading: boolean;
        onPriorityChange: (executionId: string, priority: QueuePriority) => void;
    }

    let { executions, rowCount, pagination = $bindable(), loading, onPriorityChange }: Props = $props();

    const statusColors: Record<ExecutionStatus, string> = {
        queued: 'badge-info',
        scheduled: 'badge-info',
        running: 'badge-warning',
        completed: 'badge-success',
        failed: 'badge-danger',
        timeout: 'badge-danger',
        cancelled: 'badge-neutral',
        error: 'badge-danger',
    };

    const priorityOptions = Object.values(QueuePriority);

    const column = columnHelper<AdminExecutionResponse>();
    const columns = [
        column.accessor('execution_id', {
            meta: { class: 'font-mono text-xs' },
            cell: ({ getValue }) => truncate(getValue(), 12),
        }),
        column.accessor('user_id', {
            meta: { class: 'text-xs' },
            cell: ({ getValue }) => {
                const userId = getValue();
                return userId ? truncate(userId, 12) : '-';
            },
        }),
        column.accessor('lang', { cell: ({ row }) => `${row.original.lang} ${row.original.lang_version}` }),
        column.accessor('status', { cell: ({ getValue }) => renderSnippet(statusCell, getValue()) }),
        column.accessor('priority', { cell: ({ row }) => renderSnippet(priorityCell, row.original) }),
        column.accessor('created_at', {
            meta: { class: 'text-xs' },
            cell: ({ getValue }) => formatTimestamp(getValue()),
        }),
    ];

    const table = createServerTable(columns, {
        get rows() {
            return executions;
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

{#snippet statusCell(status: ExecutionStatus)}
    <span class="badge {statusColors[status]}">{status}</span>
{/snippet}

{#snippet priorityCell(execution: AdminExecutionResponse)}
    <select
        value={execution.priority}
        onchange={(e) => onPriorityChange(execution.execution_id, e.currentTarget.value as QueuePriority)}
        class="form-select-standard text-xs py-1 px-2"
        aria-label="Priority for {execution.execution_id}"
    >
        {#each priorityOptions as priority (priority)}
            <option value={priority}>{priority}</option>
        {/each}
    </select>
{/snippet}

<DataTable {table} label="Executions" {loading} emptyText="No executions found" dense />
{#if rowCount > 0}
    <div class="mt-4 border-t divider pt-4">
        <Pagination {table} itemName="executions" pageSizeOptions={[10, 20, 50, 100]} />
    </div>
{/if}
