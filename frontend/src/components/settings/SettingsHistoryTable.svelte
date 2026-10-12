<script lang="ts">
    import { createTable, renderSnippet } from '@tanstack/svelte-table';
    import type { SettingsHistoryEntry } from '#lib/api/index.ts';
    import { formatTimestamp } from '#lib/formatters.ts';
    import { columnHelper, features } from '#lib/data-table.ts';
    import DataTable from '#components/DataTable.svelte';

    interface Props {
        history: SettingsHistoryEntry[];
        loading: boolean;
        onRestore: (timestamp: string) => void;
    }

    let { history, loading, onRestore }: Props = $props();

    const show = (value: unknown): string => (typeof value === 'object' ? JSON.stringify(value) : String(value));

    const column = columnHelper<SettingsHistoryEntry>();
    const columns = column.columns([
        column.accessor('timestamp', {
            meta: { class: 'w-36 whitespace-nowrap' },
            cell: ({ getValue }) => formatTimestamp(getValue()),
        }),
        column.accessor('field', { meta: { class: 'w-32' } }),
        column.display({
            id: 'change',
            meta: { class: 'font-mono' },
            cell: ({ row }) => renderSnippet(changeCell, row.original),
        }),
        column.display({
            id: 'actions',
            meta: { class: 'w-20' },
            cell: ({ row }) => renderSnippet(restoreCell, row.original),
        }),
    ]);

    const table = createTable({
        features,
        columns,
        get data() {
            return history;
        },
    });
</script>

{#snippet changeCell(item: SettingsHistoryEntry)}
    <div class="flex flex-wrap items-center gap-1 text-fg-muted dark:text-dark-fg-muted">
        <span class="text-red-600 dark:text-red-400 break-all">{show(item.old_value)}</span>
        <span class="mx-1">→</span>
        <span class="text-green-600 dark:text-green-400 break-all">{show(item.new_value)}</span>
    </div>
{/snippet}

{#snippet restoreCell(item: SettingsHistoryEntry)}
    <button type="button" onclick={() => onRestore(item.timestamp)} class="btn btn-ghost btn-xs">Restore</button>
{/snippet}

<DataTable
    {table}
    label="Settings history"
    {loading}
    emptyText="No settings changes recorded yet. Make some changes to your settings to see history."
    dense
/>
