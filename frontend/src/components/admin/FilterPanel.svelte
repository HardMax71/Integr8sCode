<script lang="ts">
    import { X, ChevronDown, Filter } from '@lucide/svelte';
    import type { Snippet } from 'svelte';

    interface Props {
        open: boolean;
        hasActiveFilters?: boolean;
        activeFilterCount?: number;
        onClear?: () => void;
        onApply?: () => void;
        onToggle?: () => void;
        children: Snippet;
        title?: string;
        showToggleButton?: boolean;
    }

    let {
        open = $bindable(false),
        hasActiveFilters = false,
        activeFilterCount = 0,
        onClear,
        onApply,
        onToggle,
        children,
        title = 'Filter',
        showToggleButton = true
    }: Props = $props();

    function handleToggle(): void {
        open = !open;
        onToggle?.();
    }
</script>

{#if showToggleButton}
    <button
        onclick={handleToggle}
        class="btn btn-sm sm:btn-md flex items-center gap-1 sm:gap-2 transition-all duration-200"
        class:btn-primary={open}
        class:btn-secondary-outline={!open}
        class:ring-2={open}
        class:ring-primary={open}
        class:ring-offset-2={open}
        class:dark:ring-offset-dark-bg-default={open}
    >
        <span class="transition-transform duration-200" class:rotate-180={open}>
            <Filter size={16} />
        </span>
        <span class="hidden sm:inline">Filters</span>
        {#if hasActiveFilters}
            <span class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {open ? 'bg-white text-primary' : 'bg-primary text-white'}">
                {activeFilterCount}
            </span>
        {/if}
    </button>
{/if}

{#if open}
    <div class="card mb-6">
        <div class="p-4">
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-sm font-semibold text-fg-default dark:text-dark-fg-default uppercase tracking-wide">
                    {title}
                </h3>
                <div class="flex gap-2">
                    {#if onClear}
                        <button onclick={onClear} class="btn btn-ghost btn-sm">
                            Clear All
                        </button>
                    {/if}
                    {#if onApply}
                        <button onclick={onApply} class="btn btn-primary btn-sm">
                            Apply
                        </button>
                    {/if}
                </div>
            </div>

            {@render children()}
        </div>
    </div>
{/if}
