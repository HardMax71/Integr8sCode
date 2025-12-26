<script lang="ts">
    import { EVENT_TYPES, type EventFilters as EventFiltersType } from '../../../lib/admin/events';

    interface Props {
        filters: EventFiltersType;
        onApply: () => void;
        onClear: () => void;
    }

    let {
        filters = $bindable({
            event_types: [],
            aggregate_id: '',
            correlation_id: '',
            user_id: '',
            service_name: '',
            search_text: '',
            start_time: '',
            end_time: ''
        }),
        onApply,
        onClear
    }: Props = $props();
</script>

<div class="card mb-6">
    <div class="p-4">
        <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-fg-default dark:text-dark-fg-default uppercase tracking-wide">
                Filter Events
            </h3>
            <div class="flex gap-2">
                <button onclick={onClear} class="btn btn-ghost btn-sm">
                    Clear All
                </button>
                <button onclick={onApply} class="btn btn-primary btn-sm">
                    Apply
                </button>
            </div>
        </div>

        <div class="space-y-3">
            <!-- Primary filters row -->
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                <div class="lg:col-span-1">
                    <label for="event-types-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Event Types
                    </label>
                    <select
                        id="event-types-filter"
                        bind:value={filters.event_types}
                        multiple
                        class="form-select-standard text-sm h-20"
                        title="Hold Ctrl/Cmd to select multiple"
                    >
                        {#each EVENT_TYPES as type}
                            <option value={type} class="text-xs">{type}</option>
                        {/each}
                    </select>
                </div>

                <div>
                    <label for="search-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Search
                    </label>
                    <input
                        id="search-filter"
                        type="text"
                        bind:value={filters.search_text}
                        placeholder="Search events..."
                        class="form-input-standard text-sm"
                    />
                </div>

                <div>
                    <label for="correlation-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Correlation ID
                    </label>
                    <input
                        id="correlation-filter"
                        type="text"
                        bind:value={filters.correlation_id}
                        placeholder="req_abc123"
                        class="form-input-standard text-sm font-mono"
                    />
                </div>

                <div>
                    <label for="aggregate-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Aggregate ID
                    </label>
                    <input
                        id="aggregate-filter"
                        type="text"
                        bind:value={filters.aggregate_id}
                        placeholder="exec_id"
                        class="form-input-standard text-sm font-mono"
                    />
                </div>

                <div>
                    <label for="user-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        User ID
                    </label>
                    <input
                        id="user-filter"
                        type="text"
                        bind:value={filters.user_id}
                        placeholder="user_123"
                        class="form-input-standard text-sm font-mono"
                    />
                </div>
            </div>

            <!-- Secondary filters row -->
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <div>
                    <label for="service-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Service
                    </label>
                    <input
                        id="service-filter"
                        type="text"
                        bind:value={filters.service_name}
                        placeholder="execution-service"
                        class="form-input-standard text-sm"
                    />
                </div>

                <div>
                    <label for="start-time-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Start Time
                    </label>
                    <input
                        id="start-time-filter"
                        type="datetime-local"
                        bind:value={filters.start_time}
                        class="form-input-standard text-sm"
                    />
                </div>

                <div>
                    <label for="end-time-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        End Time
                    </label>
                    <input
                        id="end-time-filter"
                        type="datetime-local"
                        bind:value={filters.end_time}
                        class="form-input-standard text-sm"
                    />
                </div>
            </div>
        </div>
    </div>
</div>
