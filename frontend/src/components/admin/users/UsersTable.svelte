<script lang="ts">
    import { renderSnippet, type PaginationState } from '@tanstack/svelte-table';
    import { Pencil, Clock, Trash } from '@lucide/svelte';
    import { UserRole, type UserResponse } from '#lib/api/index.ts';
    import { formatBoolean, formatTimestamp } from '#lib/formatters.ts';
    import { columnHelper, createServerTable } from '#lib/data-table.ts';
    import DataTable from '#components/DataTable.svelte';
    import Pagination from '#components/Pagination.svelte';

    interface Props {
        users: UserResponse[];
        rowCount: number;
        pagination: PaginationState;
        loading: boolean;
        onEdit: (user: UserResponse) => void;
        onRateLimits: (user: UserResponse) => void;
        onDelete: (user: UserResponse) => void;
    }

    let { users, rowCount, pagination = $bindable(), loading, onEdit, onRateLimits, onDelete }: Props = $props();

    const column = columnHelper<UserResponse>();
    const columns = [
        column.accessor('username', { meta: { class: 'font-medium' } }),
        column.accessor('email', {}),
        column.accessor('role', { cell: ({ row }) => renderSnippet(roleCell, row.original) }),
        column.accessor('created_at', { cell: ({ getValue }) => formatTimestamp(getValue()) }),
        column.accessor('is_active', { cell: ({ row }) => renderSnippet(statusCell, row.original) }),
        column.display({ id: 'actions', cell: ({ row }) => renderSnippet(actionsCell, row.original) }),
    ];

    const table = createServerTable(columns, {
        get rows() {
            return users;
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

{#snippet roleCell(user: UserResponse)}
    <span class="badge {user.role === UserRole.ADMIN ? 'badge-info' : 'badge-neutral'}">{user.role}</span>
{/snippet}

{#snippet statusCell(user: UserResponse)}
    <span class="badge {user.is_active ? 'badge-success' : 'badge-danger'}">
        {formatBoolean(user.is_active)}
    </span>
{/snippet}

{#snippet actionsCell(user: UserResponse)}
    <div class="flex flex-wrap gap-2">
        <button
            type="button"
            onclick={() => onEdit(user)}
            class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-green-600 hover:text-green-800 dark:text-green-400 dark:hover:text-green-300"
            title="Edit User"
            aria-label="Edit User"
        >
            <Pencil class="w-5 h-5" />
        </button>
        <button
            type="button"
            onclick={() => onRateLimits(user)}
            class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
            title="Manage Rate Limits"
            aria-label="Manage Rate Limits"
        >
            <Clock class="w-5 h-5" />
        </button>
        <button
            type="button"
            onclick={() => onDelete(user)}
            class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300"
            title="Delete User"
            aria-label="Delete User"
        >
            <Trash class="w-5 h-5" />
        </button>
    </div>
{/snippet}

<DataTable {table} label="Users" {loading} emptyText="No users found matching filters" />
{#if rowCount > 0}
    <div class="mt-4 border-t divider pt-4">
        <Pagination {table} itemName="users" pageSizeOptions={[5, 10, 20, 50]} />
    </div>
{/if}
