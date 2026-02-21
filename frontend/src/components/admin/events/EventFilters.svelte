<script lang="ts">
    import { EVENT_TYPES } from '$lib/admin/events';
    import type { EventFilter, EventType } from '$lib/api';

    interface Props {
        filters: EventFilter;
        onApply: () => void;
        onClear: () => void;
    }

    let { filters = $bindable({}), onApply, onClear }: Props = $props();
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
                        value={filters.event_types ?? []}
                        multiple
                        onchange={(e) => {
                            const sel = Array.from((e.currentTarget as HTMLSelectElement).selectedOptions).map(o => o.value as EventType);
                            filters.event_types = sel.length ? sel : null;
                        }}
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
                        value={filters.search_text ?? ''}
                        oninput={(e) => { filters.search_text = (e.currentTarget as HTMLInputElement).value || null; }}
                        placeholder="Search events..."
                        class="form-input-standard text-sm"
                    />
                </div>

                <div>
                    <label for="aggregate-filter" class="block text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Aggregate ID
                    </label>
                    <input
                        id="aggregate-filter"
                        type="text"
                        value={filters.aggregate_id ?? ''}
                        oninput={(e) => { filters.aggregate_id = (e.currentTarget as HTMLInputElement).value || null; }}
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
                        value={filters.user_id ?? ''}
                        oninput={(e) => { filters.user_id = (e.currentTarget as HTMLInputElement).value || null; }}
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
                        value={filters.service_name ?? ''}
                        oninput={(e) => { filters.service_name = (e.currentTarget as HTMLInputElement).value || null; }}
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
                        value={filters.start_time ?? ''}
                        oninput={(e) => { filters.start_time = (e.currentTarget as HTMLInputElement).value || null; }}
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
                        value={filters.end_time ?? ''}
                        oninput={(e) => { filters.end_time = (e.currentTarget as HTMLInputElement).value || null; }}
                        class="form-input-standard text-sm"
                    />
                </div>
            </div>
        </div>
    </div>
</div>
