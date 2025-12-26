<script lang="ts">
    import { ChevronDown } from '@lucide/svelte';

    interface AdvancedFilters {
        bypassRateLimit: string;
        hasCustomLimits: string;
        globalMultiplier: string;
    }

    interface Props {
        searchQuery: string;
        roleFilter: string;
        statusFilter: string;
        advancedFilters: AdvancedFilters;
        showAdvancedFilters: boolean;
        hasFiltersActive: boolean;
        onReset: () => void;
    }

    let {
        searchQuery = $bindable(''),
        roleFilter = $bindable('all'),
        statusFilter = $bindable('all'),
        advancedFilters = $bindable({ bypassRateLimit: 'all', hasCustomLimits: 'all', globalMultiplier: 'all' }),
        showAdvancedFilters = $bindable(false),
        hasFiltersActive,
        onReset
    }: Props = $props();
</script>

<div class="card mb-4">
    <div class="p-3 sm:p-4">
        <div class="flex flex-col lg:flex-row gap-3 lg:gap-4 lg:items-end">
            <div class="w-full lg:flex-1 lg:max-w-md">
                <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Search</label>
                <input
                    id="user-search"
                    type="text"
                    bind:value={searchQuery}
                    placeholder="Search by username, email, or ID..."
                    class="input w-full"
                    autocomplete="off"
                    autocorrect="off"
                    autocapitalize="off"
                    spellcheck="false"
                />
            </div>
            <div class="w-full sm:w-auto sm:min-w-[140px]">
                <label for="role-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Role</label>
                <select id="role-filter" bind:value={roleFilter} class="form-select-standard w-full">
                    <option value="all">All Roles</option>
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                </select>
            </div>
            <div class="w-full sm:w-auto sm:min-w-[140px]">
                <label for="status-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Status</label>
                <select id="status-filter" bind:value={statusFilter} class="form-select-standard w-full">
                    <option value="all">All Status</option>
                    <option value="active">Active</option>
                    <option value="disabled">Disabled</option>
                </select>
            </div>
            <button
                onclick={() => showAdvancedFilters = !showAdvancedFilters}
                class="btn btn-outline flex items-center gap-2 w-full sm:w-auto justify-center"
            >
                <ChevronDown class="w-4 h-4 transition-transform {showAdvancedFilters ? 'rotate-180' : ''}" />
                Advanced
            </button>
            <button
                onclick={onReset}
                class="btn btn-outline w-full sm:w-auto"
                disabled={!hasFiltersActive}
            >
                Reset
            </button>
        </div>

        {#if showAdvancedFilters}
            <div class="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-700">
                <h4 class="text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-3">Rate Limit Filters</h4>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                        <label for="bypass-rate-limit-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Bypass Rate Limit</label>
                        <select id="bypass-rate-limit-filter" bind:value={advancedFilters.bypassRateLimit} class="form-select-standard w-full">
                            <option value="all">All</option>
                            <option value="yes">Yes (Bypassed)</option>
                            <option value="no">No (Limited)</option>
                        </select>
                    </div>
                    <div>
                        <label for="custom-limits-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Custom Limits</label>
                        <select id="custom-limits-filter" bind:value={advancedFilters.hasCustomLimits} class="form-select-standard w-full">
                            <option value="all">All</option>
                            <option value="yes">Has Custom</option>
                            <option value="no">Default Only</option>
                        </select>
                    </div>
                    <div>
                        <label for="global-multiplier-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Global Multiplier</label>
                        <select id="global-multiplier-filter" bind:value={advancedFilters.globalMultiplier} class="form-select-standard w-full">
                            <option value="all">All</option>
                            <option value="custom">Custom (≠ 1.0)</option>
                            <option value="default">Default (= 1.0)</option>
                        </select>
                    </div>
                </div>
            </div>
        {/if}
    </div>
</div>
