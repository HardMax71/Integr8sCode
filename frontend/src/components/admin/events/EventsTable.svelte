<script lang="ts">
    import { renderSnippet, type PaginationState } from '@tanstack/svelte-table';
    import { Eye, Play, Trash } from '@lucide/svelte';
    import type { BrowsedEvent } from '#lib/admin/stores/eventsStore.svelte.ts';
    import { formatDateOnly, formatTimeOnly } from '#lib/formatters.ts';
    import { getEventTypeColor } from '#lib/admin/events/index.ts';
    import { columnHelper, createServerTable } from '#lib/data-table.ts';
    import DataTable from '#components/DataTable.svelte';
    import Pagination from '#components/Pagination.svelte';
    import EventTypeIcon from '#components/EventTypeIcon.svelte';

    interface Props {
        events: BrowsedEvent[];
        rowCount: number;
        pagination: PaginationState;
        loading: boolean;
        onViewDetails: (eventId: string) => void;
        onPreviewReplay: (eventId: string) => void;
        onReplay: (eventId: string) => void;
        onDelete: (eventId: string) => void;
        onViewUser: (userId: string) => void;
    }

    let {
        events,
        rowCount,
        pagination = $bindable(),
        loading,
        onViewDetails,
        onPreviewReplay,
        onReplay,
        onDelete,
        onViewUser,
    }: Props = $props();

    const column = columnHelper<BrowsedEvent>();
    const columns = [
        column.display({ id: 'time', header: 'Time', cell: ({ row }) => renderSnippet(timeCell, row.original) }),
        column.display({ id: 'type', header: 'Type', cell: ({ row }) => renderSnippet(typeCell, row.original) }),
        column.display({ id: 'user', header: 'User', cell: ({ row }) => renderSnippet(userCell, row.original) }),
        column.display({
            id: 'service',
            header: 'Service',
            meta: { class: 'hidden xl:table-cell' },
            cell: ({ row }) => renderSnippet(serviceCell, row.original),
        }),
        column.display({
            id: 'actions',
            header: 'Actions',
            meta: { class: 'text-center' },
            cell: ({ row }) => renderSnippet(actionsCell, row.original),
        }),
    ];

    const table = createServerTable(columns, {
        get rows() {
            return events;
        },
        get rowCount() {
            return rowCount;
        },
        get pagination() {
            return pagination;
        },
        set pagination(next) {
            pagination = next;
        },
    });
</script>

{#snippet timeCell(event: BrowsedEvent)}
    <button
        type="button"
        class="text-left hover:underline"
        onclick={() => onViewDetails(event.event_id)}
        aria-label="View details for event {event.event_id.slice(0, 8)}"
    >
        <div class="text-xs text-fg-muted dark:text-dark-fg-muted">{formatDateOnly(event.timestamp)}</div>
        <div class="text-sm">{formatTimeOnly(event.timestamp)}</div>
    </button>
{/snippet}

{#snippet typeCell(event: BrowsedEvent)}
    <div class="relative group">
        <span
            class="{getEventTypeColor(event.event_type)} shrink-0 cursor-help"
            data-testid="event-type-icon"
            data-event-type={event.event_type}
        >
            <EventTypeIcon eventType={event.event_type} />
        </span>
        <div
            class="absolute z-10 invisible group-hover:visible bg-tooltip-bg text-white text-xs rounded py-1 px-2 left-0 top-8 min-w-max"
        >
            <div class="font-medium">{event.event_type}</div>
            <div class="text-neutral-400 text-[10px] font-mono mt-0.5">{event.event_id.slice(0, 8)}...</div>
            <div class="absolute -top-1 left-2 w-2 h-2 bg-tooltip-bg transform rotate-45"></div>
        </div>
    </div>
{/snippet}

{#snippet userCell(event: BrowsedEvent)}
    {#if event.metadata?.user_id}
        {@const userId = event.metadata.user_id}
        <button
            type="button"
            class="text-blue-600 dark:text-blue-400 hover:underline text-left font-mono text-xs truncate"
            title="View user overview"
            onclick={() => onViewUser(userId)}
        >
            {userId}
        </button>
    {:else}
        <span class="text-fg-muted dark:text-dark-fg-muted">-</span>
    {/if}
{/snippet}

{#snippet serviceCell(event: BrowsedEvent)}
    <div class="truncate" title={event.metadata?.service_name || '-'}>{event.metadata?.service_name || '-'}</div>
{/snippet}

{#snippet actionsCell(event: BrowsedEvent)}
    <div class="flex flex-wrap gap-1 justify-center">
        <button
            type="button"
            onclick={() => onPreviewReplay(event.event_id)}
            class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded"
            title="Preview replay"
            aria-label="Preview replay"
        >
            <Eye size={16} />
        </button>
        <button
            type="button"
            onclick={() => onReplay(event.event_id)}
            class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-blue-600 dark:text-blue-400"
            title="Replay"
            aria-label="Replay"
        >
            <Play size={16} />
        </button>
        <button
            type="button"
            onclick={() => onDelete(event.event_id)}
            class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-red-600 dark:text-red-400"
            title="Delete"
            aria-label="Delete"
        >
            <Trash size={16} />
        </button>
    </div>
{/snippet}

<DataTable {table} label="Events" {loading} emptyText="No events found" dense />
<Pagination {table} itemName="events" />
