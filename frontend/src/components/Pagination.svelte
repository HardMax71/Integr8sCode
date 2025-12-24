<script lang="ts">
  import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from '@lucide/svelte';

  interface Props {
    currentPage: number;
    totalPages: number;
    totalItems: number;
    pageSize: number;
    onPageChange: (page: number) => void;
    onPageSizeChange?: (size: number) => void;
    pageSizeOptions?: number[];
    itemName?: string;
  }

  let {
    currentPage,
    totalPages,
    totalItems,
    pageSize,
    onPageChange,
    onPageSizeChange,
    pageSizeOptions = [10, 25, 50, 100],
    itemName = 'items',
  }: Props = $props();

  const start = $derived((currentPage - 1) * pageSize + 1);
  const end = $derived(Math.min(currentPage * pageSize, totalItems));
</script>

{#if totalPages > 1 || onPageSizeChange}
  <div class="pagination-container">
    <div class="pagination-info">
      Showing {start} - {end} of {totalItems} {itemName}
    </div>

    <div class="flex items-center gap-4">
      {#if onPageSizeChange}
        <select
          class="pagination-selector"
          value={pageSize}
          onchange={(e) => onPageSizeChange?.(Number(e.currentTarget.value))}
        >
          {#each pageSizeOptions as size}
            <option value={size}>{size} / page</option>
          {/each}
        </select>
      {/if}

      {#if totalPages > 1}
        <div class="pagination-controls">
          <button
            class="pagination-button"
            onclick={() => onPageChange(1)}
            disabled={currentPage === 1}
            aria-label="First page"
          >
            <ChevronsLeft size={16} />
          </button>
          <button
            class="pagination-button"
            onclick={() => onPageChange(currentPage - 1)}
            disabled={currentPage === 1}
            aria-label="Previous page"
          >
            <ChevronLeft size={16} />
          </button>
          <span class="pagination-text">
            <span class="font-medium">{currentPage}</span> / <span class="font-medium">{totalPages}</span>
          </span>
          <button
            class="pagination-button"
            onclick={() => onPageChange(currentPage + 1)}
            disabled={currentPage === totalPages}
            aria-label="Next page"
          >
            <ChevronRight size={16} />
          </button>
          <button
            class="pagination-button"
            onclick={() => onPageChange(totalPages)}
            disabled={currentPage === totalPages}
            aria-label="Last page"
          >
            <ChevronsRight size={16} />
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
