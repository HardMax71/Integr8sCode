<script lang="ts">
    import { X } from '@lucide/svelte';
    import { SagaState } from '#lib/api/index.ts';
    import type { SagaStateFilter } from '#lib/admin/sagas/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';

    interface Props {
        searchQuery: string;
        stateFilter: SagaStateFilter;
        executionIdFilter: string;
        onClear: () => void;
    }

    let {
        searchQuery = $bindable(''),
        stateFilter = $bindable<SagaStateFilter>(''),
        executionIdFilter = $bindable(''),
        onClear,
    }: Props = $props();
</script>

<div class="mb-6 flex flex-col lg:grid lg:grid-cols-4 gap-3">
    <div>
        <label for="saga-search" class="block text-sm font-medium mb-2 text-fg-muted">{fieldTitle('search')}</label>
        <input id="saga-search" type="text" bind:value={searchQuery} class="form-input-standard" />
    </div>
    <div>
        <label for="saga-state-filter" class="block text-sm font-medium mb-2 text-fg-muted">{fieldTitle('state')}</label
        >
        <select id="saga-state-filter" bind:value={stateFilter} class="form-select-standard">
            <option value="">All</option>
            {#each Object.values(SagaState) as state (state)}
                <option value={state}>{state}</option>
            {/each}
        </select>
    </div>
    <div>
        <label for="saga-execution-filter" class="block text-sm font-medium mb-2 text-fg-muted"
            >{fieldTitle('execution_id')}</label
        >
        <input id="saga-execution-filter" type="text" bind:value={executionIdFilter} class="form-input-standard" />
    </div>
    <div>
        <span class="block text-sm font-medium mb-2 text-fg-muted">Actions</span>
        <button type="button" onclick={onClear} class="w-full btn btn-secondary-outline">
            <X class="w-4 h-4 mr-1.5" />Clear Filters
        </button>
    </div>
</div>
