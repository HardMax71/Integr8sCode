<script lang="ts" generics="TData extends RowData">
    import type { RowData } from '@tanstack/svelte-table';
    import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from '@lucide/svelte';
    import type { AppTable } from '#lib/data-table.ts';

    interface Props {
        table: AppTable<TData>;
        itemName: string;
        pageSizeOptions?: number[];
    }

    let { table, itemName, pageSizeOptions = [10, 25, 50, 100] }: Props = $props();

    const pagination = $derived(table.atoms.pagination.get());
    const rowCount = $derived(table.getRowCount());
    const pageCount = $derived(table.getPageCount());
    const start = $derived(Math.min(pagination.pageIndex * pagination.pageSize + 1, rowCount));
    const end = $derived(Math.min((pagination.pageIndex + 1) * pagination.pageSize, rowCount));
</script>

{#if rowCount > 0}
    <div class="pagination-container">
        <div class="pagination-info">Showing {start} - {end} of {rowCount} {itemName}</div>

        <div class="flex items-center gap-4">
            <select
                class="pagination-selector"
                value={pagination.pageSize}
                onchange={(e) => table.setPageSize(Number(e.currentTarget.value))}
                aria-label="Items per page"
            >
                {#each pageSizeOptions as size (size)}
                    <option value={size}>{size} / page</option>
                {/each}
            </select>

            {#if pageCount > 1}
                <div class="pagination-controls">
                    <button
                        type="button"
                        class="pagination-button"
                        onclick={() => table.firstPage()}
                        disabled={!table.getCanPreviousPage()}
                        aria-label="First page"
                    >
                        <ChevronsLeft size={16} />
                    </button>
                    <button
                        type="button"
                        class="pagination-button"
                        onclick={() => table.previousPage()}
                        disabled={!table.getCanPreviousPage()}
                        aria-label="Previous page"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    <span class="pagination-text">
                        <span class="font-medium">{pagination.pageIndex + 1}</span> /
                        <span class="font-medium">{pageCount}</span>
                    </span>
                    <button
                        type="button"
                        class="pagination-button"
                        onclick={() => table.nextPage()}
                        disabled={!table.getCanNextPage()}
                        aria-label="Next page"
                    >
                        <ChevronRight size={16} />
                    </button>
                    <button
                        type="button"
                        class="pagination-button"
                        onclick={() => table.lastPage()}
                        disabled={!table.getCanLastPage()}
                        aria-label="Last page"
                    >
                        <ChevronsRight size={16} />
                    </button>
                </div>
            {/if}
        </div>
    </div>
{/if}
