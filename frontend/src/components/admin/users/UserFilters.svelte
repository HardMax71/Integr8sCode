<script lang="ts" module>
    import type { ListUsersApiV1AdminUsersGetData } from '#lib/api/index.ts';

    type UserQuery = NonNullable<ListUsersApiV1AdminUsersGetData['query']>;
    export type UserListFilters = Required<
        Pick<
            UserQuery,
            'search' | 'role' | 'is_active' | 'bypass_rate_limit' | 'has_custom_limits' | 'custom_multiplier'
        >
    >;
</script>

<script lang="ts">
    import { ChevronDown } from '@lucide/svelte';
    import { UserRole } from '#lib/api/index.ts';
    import { fieldTitle, formatBoolean } from '#lib/formatters.ts';

    type BooleanFilter = 'is_active' | 'bypass_rate_limit' | 'has_custom_limits' | 'custom_multiplier';

    interface Props {
        filters: UserListFilters;
        showAdvancedFilters: boolean;
        hasFiltersActive: boolean;
        onReset: () => void;
    }

    let { filters = $bindable(), showAdvancedFilters = $bindable(false), hasFiltersActive, onReset }: Props = $props();
</script>

{#snippet booleanFilter(key: BooleanFilter)}
    <label for="{key}-filter">{fieldTitle(key)}</label>
    <select id="{key}-filter" bind:value={filters[key]} class="form-select-standard w-full">
        <option value={null}>All</option>
        <option value={true}>{formatBoolean(true)}</option>
        <option value={false}>{formatBoolean(false)}</option>
    </select>
{/snippet}

<div class="card mb-4">
    <div class="p-3 sm:p-4">
        <div class="flex flex-col lg:flex-row gap-3 lg:gap-4 lg:items-end">
            <div class="field w-full lg:flex-1 lg:max-w-md">
                <label for="search-filter">{fieldTitle('search')}</label>
                <input
                    id="search-filter"
                    type="text"
                    bind:value={filters.search}
                    class="w-full"
                    autocomplete="off"
                    autocorrect="off"
                    autocapitalize="off"
                    spellcheck="false"
                />
            </div>
            <div class="field w-full sm:w-auto sm:min-w-35">
                <label for="role-filter">{fieldTitle('role')}</label>
                <select id="role-filter" bind:value={filters.role} class="form-select-standard w-full">
                    <option value={null}>All</option>
                    {#each Object.values(UserRole) as role (role)}
                        <option value={role}>{role}</option>
                    {/each}
                </select>
            </div>
            <div class="field w-full sm:w-auto sm:min-w-35">
                {@render booleanFilter('is_active')}
            </div>
            <button
                type="button"
                onclick={() => (showAdvancedFilters = !showAdvancedFilters)}
                class="btn btn-secondary-outline gap-2 w-full sm:w-auto"
            >
                <ChevronDown class="size-4 transition-transform {showAdvancedFilters ? 'rotate-180' : ''}" />
                Advanced
            </button>
            <button
                type="button"
                onclick={onReset}
                class="btn btn-secondary-outline w-full sm:w-auto"
                disabled={!hasFiltersActive}
            >
                Reset
            </button>
        </div>

        {#if showAdvancedFilters}
            <div class="mt-4 pt-4 border-t">
                <h4 class="text-sm font-medium text-fg-muted mb-3">Rate Limit Filters</h4>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>{@render booleanFilter('bypass_rate_limit')}</div>
                    <div>{@render booleanFilter('has_custom_limits')}</div>
                    <div>{@render booleanFilter('custom_multiplier')}</div>
                </div>
            </div>
        {/if}
    </div>
</div>
