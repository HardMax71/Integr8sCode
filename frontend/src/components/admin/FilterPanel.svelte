<script lang="ts">
    import { Funnel } from '@lucide/svelte';
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
        showToggleButton = true,
    }: Props = $props();

    function handleToggle(): void {
        open = !open;
        onToggle?.();
    }
</script>

{#if showToggleButton}
    <button
        type="button"
        onclick={handleToggle}
        aria-expanded={open}
        class={[
            'btn btn-sm gap-1 sm:gap-2',
            open ? 'btn-primary ring-2 ring-primary ring-offset-2 ring-offset-page' : 'btn-secondary-outline',
        ]}
    >
        <span class="transition-transform duration-200" class:rotate-180={open}>
            <Funnel size={16} />
        </span>
        <span class="hidden sm:inline">Filters</span>
        {#if hasActiveFilters}
            <span
                class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs font-bold {open
                    ? 'bg-surface text-accent'
                    : 'bg-primary text-white'}"
            >
                {activeFilterCount}
            </span>
        {/if}
    </button>
{/if}

{#if open}
    <div class="card mb-6">
        <div class="p-4">
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-sm font-semibold text-fg uppercase tracking-wide">
                    {title}
                </h3>
                <div class="flex gap-2">
                    {#if onClear}
                        <button type="button" onclick={onClear} class="btn btn-ghost btn-sm"> Clear All </button>
                    {/if}
                    {#if onApply}
                        <button type="button" onclick={onApply} class="btn btn-primary btn-sm"> Apply </button>
                    {/if}
                </div>
            </div>

            {@render children()}
        </div>
    </div>
{/if}
