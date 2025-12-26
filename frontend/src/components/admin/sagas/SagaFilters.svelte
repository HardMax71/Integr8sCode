<script lang="ts">
    import { X } from '@lucide/svelte';
    import { SAGA_STATES } from '../../../lib/admin/sagas';

    interface Props {
        searchQuery: string;
        stateFilter: string;
        executionIdFilter: string;
        onSearch: () => void;
        onClear: () => void;
    }

    let {
        searchQuery = $bindable(''),
        stateFilter = $bindable(''),
        executionIdFilter = $bindable(''),
        onSearch,
        onClear
    }: Props = $props();
</script>

<div class="mb-6 flex flex-col lg:grid lg:grid-cols-4 gap-3">
    <div>
        <label for="saga-search" class="block text-sm font-medium mb-2 text-fg-muted">Search</label>
        <input
            id="saga-search"
            type="text"
            bind:value={searchQuery}
            oninput={onSearch}
            placeholder="Search by ID, name, or error..."
            class="form-input-standard"
        />
    </div>
    <div>
        <label for="saga-state-filter" class="block text-sm font-medium mb-2 text-fg-muted">State</label>
        <select id="saga-state-filter" bind:value={stateFilter} class="form-select-standard">
            <option value="">All States</option>
            {#each Object.entries(SAGA_STATES) as [value, state]}
                <option value={value}>{state.label}</option>
            {/each}
        </select>
    </div>
    <div>
        <label for="saga-execution-filter" class="block text-sm font-medium mb-2 text-fg-muted">Execution ID</label>
        <input
            id="saga-execution-filter"
            type="text"
            bind:value={executionIdFilter}
            oninput={onSearch}
            placeholder="Filter by execution ID..."
            class="form-input-standard"
        />
    </div>
    <div>
        <span class="block text-sm font-medium mb-2 text-fg-muted">Actions</span>
        <button onclick={onClear} class="w-full btn btn-secondary-outline">
            <X class="w-4 h-4 mr-1.5" />Clear Filters
        </button>
    </div>
</div>
