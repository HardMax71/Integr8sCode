<script lang="ts" module>
    import type { ListSagasApiV1SagasGetData } from '#lib/api/index.ts';

    export type SagaListFilters = Required<
        Pick<NonNullable<ListSagasApiV1SagasGetData['query']>, 'search' | 'state' | 'execution_id'>
    >;
</script>

<script lang="ts">
    import { X } from '@lucide/svelte';
    import { SagaState } from '#lib/api/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';

    interface Props {
        filters: SagaListFilters;
        onClear: () => void;
    }

    let { filters = $bindable(), onClear }: Props = $props();
</script>

<div class="mb-6 flex flex-col lg:grid lg:grid-cols-4 gap-3">
    <div class="field">
        <label for="saga-search">{fieldTitle('search')}</label>
        <input id="saga-search" type="text" bind:value={filters.search} class="form-input-standard" />
    </div>
    <div class="field">
        <label for="saga-state-filter">{fieldTitle('state')}</label>
        <select id="saga-state-filter" bind:value={filters.state} class="form-select-standard">
            <option value={null}>All</option>
            {#each Object.values(SagaState) as state (state)}
                <option value={state}>{state}</option>
            {/each}
        </select>
    </div>
    <div class="field">
        <label for="saga-execution-filter">{fieldTitle('execution_id')}</label>
        <input id="saga-execution-filter" type="text" bind:value={filters.execution_id} class="form-input-standard" />
    </div>
    <div>
        <span class="block text-sm font-medium mb-2 text-fg-muted">Actions</span>
        <button type="button" onclick={onClear} class="w-full btn btn-secondary-outline">
            <X class="size-4 mr-1.5" />Clear Filters
        </button>
    </div>
</div>
