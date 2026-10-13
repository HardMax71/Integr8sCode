<script lang="ts">
    import { format, parseISO } from 'date-fns';
    import { EVENT_TYPES } from '#lib/admin/events/index.ts';
    import type { EventFilter, EventType } from '#lib/api/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';

    interface Props {
        filters: EventFilter;
        onApply: () => void;
        onClear: () => void;
    }

    let { filters = $bindable({}), onApply, onClear }: Props = $props();

    // A datetime-local input holds local wall time with no offset, which is what parseISO and format read and write
    const LOCAL_DATETIME = "yyyy-MM-dd'T'HH:mm";

    function inputValue(timestamp: string | null | undefined): string {
        return timestamp ? format(parseISO(timestamp), LOCAL_DATETIME) : '';
    }

    function fromInput(e: Event): string | null {
        const value = (e.currentTarget as HTMLInputElement).value;
        return value ? parseISO(value).toISOString() : null;
    }
</script>

<div class="card mb-6">
    <div class="p-4">
        <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold uppercase tracking-wide">Filter Events</h3>
            <div class="flex gap-2">
                <button type="button" onclick={onClear} class="btn btn-ghost btn-sm"> Clear All </button>
                <button type="button" onclick={onApply} class="btn btn-primary btn-sm"> Apply </button>
            </div>
        </div>

        <div class="space-y-3">
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                <div class="field lg:col-span-1">
                    <label for="event-types-filter">
                        {fieldTitle('event_types')}
                    </label>
                    <select
                        id="event-types-filter"
                        multiple
                        onchange={(e) => {
                            const sel = Array.from((e.currentTarget as HTMLSelectElement).selectedOptions).map(
                                (o) => o.value as EventType,
                            );
                            filters.event_types = sel.length ? sel : null;
                        }}
                        class="form-select-standard text-sm h-20"
                        title="Hold Ctrl/Cmd to select multiple"
                    >
                        {#each EVENT_TYPES as type (type)}
                            <option value={type} selected={filters.event_types?.includes(type) ?? false} class="text-xs"
                                >{type}</option
                            >
                        {/each}
                    </select>
                </div>

                <div class="field">
                    <label for="search-filter">
                        {fieldTitle('search_text')}
                    </label>
                    <input
                        id="search-filter"
                        type="text"
                        value={filters.search_text ?? ''}
                        oninput={(e) => {
                            filters.search_text = (e.currentTarget as HTMLInputElement).value || null;
                        }}
                        class="form-input-standard text-sm"
                    />
                </div>

                <div class="field">
                    <label for="aggregate-filter">
                        {fieldTitle('aggregate_id')}
                    </label>
                    <input
                        id="aggregate-filter"
                        type="text"
                        value={filters.aggregate_id ?? ''}
                        oninput={(e) => {
                            filters.aggregate_id = (e.currentTarget as HTMLInputElement).value || null;
                        }}
                        placeholder="exec_id"
                        class="form-input-standard text-sm font-mono"
                    />
                </div>

                <div class="field">
                    <label for="user-filter">
                        {fieldTitle('user_id')}
                    </label>
                    <input
                        id="user-filter"
                        type="text"
                        value={filters.user_id ?? ''}
                        oninput={(e) => {
                            filters.user_id = (e.currentTarget as HTMLInputElement).value || null;
                        }}
                        placeholder="user_123"
                        class="form-input-standard text-sm font-mono"
                    />
                </div>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <div class="field">
                    <label for="service-filter">
                        {fieldTitle('service_name')}
                    </label>
                    <input
                        id="service-filter"
                        type="text"
                        value={filters.service_name ?? ''}
                        oninput={(e) => {
                            filters.service_name = (e.currentTarget as HTMLInputElement).value || null;
                        }}
                        placeholder="execution-service"
                        class="form-input-standard text-sm"
                    />
                </div>

                <div class="field">
                    <label for="start-time-filter">
                        {fieldTitle('start_time')}
                    </label>
                    <input
                        id="start-time-filter"
                        type="datetime-local"
                        value={inputValue(filters.start_time)}
                        oninput={(e) => {
                            filters.start_time = fromInput(e);
                        }}
                        class="form-input-standard text-sm"
                    />
                </div>

                <div class="field">
                    <label for="end-time-filter">
                        {fieldTitle('end_time')}
                    </label>
                    <input
                        id="end-time-filter"
                        type="datetime-local"
                        value={inputValue(filters.end_time)}
                        oninput={(e) => {
                            filters.end_time = fromInput(e);
                        }}
                        class="form-input-standard text-sm"
                    />
                </div>
            </div>
        </div>
    </div>
</div>
