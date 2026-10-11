<script lang="ts" generics="TData extends RowData">
    import { FlexRender, type RowData } from '@tanstack/svelte-table';
    import type { AppTable } from '#lib/data-table.ts';
    import Spinner from '#components/Spinner.svelte';

    interface Props {
        table: AppTable<TData>;
        /** Names the table for screen readers */
        label: string;
        loading?: boolean;
        emptyText: string;
        /** Smaller cell padding */
        dense?: boolean;
        /** Below the lg breakpoint, show a card per row instead of the table */
        cards?: boolean;
    }

    let { table, label, loading = false, emptyText, dense = false, cards = true }: Props = $props();

    const rows = $derived(table.getRowModel().rows);
    const headerCell = $derived(dense ? 'table-header-cell-sm' : 'table-header-cell');
    const bodyCell = $derived(dense ? 'table-cell-sm' : 'table-cell');
</script>

{#if loading && rows.length === 0}
    <div class="empty-state">
        <Spinner size="large" className="mx-auto mb-4" />
        <p>Loading {label.toLowerCase()}...</p>
    </div>
{:else if rows.length === 0}
    <p class="empty-state">{emptyText}</p>
{:else}
    <div class="overflow-x-auto {cards ? 'hidden lg:block' : ''}">
        <table class="table" aria-label={label}>
            <thead class="table-header">
                {#each table.getHeaderGroups() as group (group.id)}
                    <tr>
                        {#each group.headers as header (header.id)}
                            <th scope="col" class="{headerCell} {header.column.columnDef.meta?.class ?? ''}">
                                {#if !header.isPlaceholder}<FlexRender {header} />{/if}
                            </th>
                        {/each}
                    </tr>
                {/each}
            </thead>
            <tbody class="table-body">
                {#each rows as row (row.id)}
                    <tr class="table-row">
                        {#each row.getAllCells() as cell (cell.id)}
                            <td class="{bodyCell} {cell.column.columnDef.meta?.class ?? ''}"><FlexRender {cell} /></td>
                        {/each}
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>

    {#if cards}
        <ul class="lg:hidden divide-y divide-border-default dark:divide-dark-border-default" aria-label={label}>
            {#each rows as row (row.id)}
                <li class="p-4">
                    <dl class="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
                        {#each row.getAllCells() as cell (cell.id)}
                            {@const header = cell.column.columnDef.header}
                            <dt class="text-fg-muted dark:text-dark-fg-muted">
                                {typeof header === 'string' ? header : ''}
                            </dt>
                            <dd class="min-w-0 wrap-anywhere text-fg-default dark:text-dark-fg-default">
                                <FlexRender {cell} />
                            </dd>
                        {/each}
                    </dl>
                </li>
            {/each}
        </ul>
    {/if}
{/if}
