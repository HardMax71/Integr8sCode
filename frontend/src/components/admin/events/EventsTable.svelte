<script lang="ts">
    import { Eye, Play, Trash2 } from '@lucide/svelte';
    import type { EventBrowseResponse } from '$lib/api';
    import { formatTimestamp } from '$lib/formatters';
    import { getEventTypeColor } from '$lib/admin/events';
    import EventTypeIcon from '$components/EventTypeIcon.svelte';

    type BrowsedEvent = EventBrowseResponse['events'][number];

    interface Props {
        events: BrowsedEvent[];
        onViewDetails: (eventId: string) => void;
        onPreviewReplay: (eventId: string) => void;
        onReplay: (eventId: string) => void;
        onDelete: (eventId: string) => void;
        onViewUser: (userId: string) => void;
    }

    let { events, onViewDetails, onPreviewReplay, onReplay, onDelete, onViewUser }: Props = $props();
</script>

<!-- Desktop view - Table -->
<div class="hidden md:block overflow-x-auto">
    <table class="w-full divide-y divide-border-default dark:divide-dark-border-default">
        <thead class="bg-neutral-50 dark:bg-neutral-900">
            <tr>
                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Time</th>
                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Type</th>
                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider hidden lg:table-cell">User</th>
                <th class="px-3 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider hidden xl:table-cell">Service</th>
                <th class="px-3 py-2 text-center text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Actions</th>
            </tr>
        </thead>
        <tbody class="bg-bg-default dark:bg-dark-bg-default divide-y divide-border-default dark:divide-dark-border-default">
            {#each events as event}
                <tr
                    class="hover:bg-neutral-50 dark:hover:bg-neutral-800 cursor-pointer transition-colors border-b border-border-default dark:border-dark-border-default"
                    onclick={() => onViewDetails(event.event_id)}
                    onkeydown={(e) => e.key === 'Enter' && onViewDetails(event.event_id)}
                    tabindex="0"
                    role="button"
                    aria-label="View event details"
                >
                    <td class="px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                        <div class="text-xs text-fg-muted dark:text-dark-fg-muted">
                            {new Date(event.timestamp).toLocaleDateString()}
                        </div>
                        <div class="text-sm">
                            {new Date(event.timestamp).toLocaleTimeString()}
                        </div>
                    </td>
                    <td class="px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                        <div class="relative group">
                            <span class="{getEventTypeColor(event.event_type)} shrink-0 cursor-help">
                                <EventTypeIcon eventType={event.event_type} />
                            </span>
                            <!-- Tooltip on hover -->
                            <div class="absolute z-10 invisible group-hover:visible bg-tooltip-bg text-white text-xs rounded py-1 px-2 left-0 top-8 min-w-max">
                                <div class="font-medium">{event.event_type}</div>
                                <div class="text-neutral-400 text-[10px] font-mono mt-0.5">
                                    {event.event_id.slice(0, 8)}...
                                </div>
                                <div class="absolute -top-1 left-2 w-2 h-2 bg-tooltip-bg transform rotate-45"></div>
                            </div>
                        </div>
                    </td>
                    <td class="table-cell-sm hidden lg:table-cell">
                        {#if event.metadata?.user_id}
                            <button
                                class="text-blue-600 dark:text-blue-400 hover:underline text-left"
                                title="View user overview"
                                onclick={(e) => { e.stopPropagation(); if (event.metadata.user_id) onViewUser(event.metadata.user_id); }}
                            >
                                <div class="font-mono text-xs truncate">
                                    {event.metadata.user_id}
                                </div>
                            </button>
                        {:else}
                            <span class="text-fg-muted dark:text-dark-fg-muted">-</span>
                        {/if}
                    </td>
                    <td class="table-cell-sm hidden xl:table-cell">
                        <div class="truncate" title={event.metadata?.service_name || '-'}>
                            {event.metadata?.service_name || '-'}
                        </div>
                    </td>
                    <td class="px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                        <div class="flex gap-1 justify-center">
                            <button
                                onclick={(e) => { e.stopPropagation(); onPreviewReplay(event.event_id); }}
                                class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded"
                                title="Preview replay"
                            >
                                <Eye size={16} />
                            </button>
                            <button
                                onclick={(e) => { e.stopPropagation(); onReplay(event.event_id); }}
                                class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-blue-600 dark:text-blue-400"
                                title="Replay"
                            >
                                <Play size={16} />
                            </button>
                            <button
                                onclick={(e) => { e.stopPropagation(); onDelete(event.event_id); }}
                                class="p-1 hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover rounded text-red-600 dark:text-red-400"
                                title="Delete"
                            >
                                <Trash2 size={16} />
                            </button>
                        </div>
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
</div>

<!-- Mobile view - Cards -->
<div class="md:hidden space-y-3">
    {#each events as event}
        <div
            class="mobile-card"
            onclick={() => onViewDetails(event.event_id)}
            onkeydown={(e) => e.key === 'Enter' && onViewDetails(event.event_id)}
            tabindex="0"
            role="button"
            aria-label="View event details"
        >
            <div class="flex justify-between items-start mb-2">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <div class="relative group">
                            <span class="{getEventTypeColor(event.event_type)} shrink-0 cursor-help">
                                <EventTypeIcon eventType={event.event_type} />
                            </span>
                            <div class="absolute z-10 invisible group-hover:visible bg-tooltip-bg text-white text-xs rounded py-1 px-2 left-0 top-7 min-w-max">
                                <div class="font-medium">{event.event_type}</div>
                                <div class="text-neutral-400 text-[10px] font-mono mt-0.5">
                                    {event.event_id.slice(0, 8)}...
                                </div>
                                <div class="absolute -top-1 left-2 w-2 h-2 bg-tooltip-bg transform rotate-45"></div>
                            </div>
                        </div>
                        <div class="text-sm text-fg-muted dark:text-dark-fg-muted">
                            {formatTimestamp(event.timestamp)}
                        </div>
                    </div>
                </div>
                <div class="flex gap-1 ml-2">
                    <button
                        onclick={(e) => { e.stopPropagation(); onPreviewReplay(event.event_id); }}
                        class="btn btn-ghost btn-xs p-1"
                        title="Preview replay"
                    >
                        <Eye size={16} />
                    </button>
                    <button
                        onclick={(e) => { e.stopPropagation(); onReplay(event.event_id); }}
                        class="btn btn-ghost btn-xs p-1 text-blue-600 dark:text-blue-400"
                        title="Replay"
                    >
                        <Play size={16} />
                    </button>
                    <button
                        onclick={(e) => { e.stopPropagation(); onDelete(event.event_id); }}
                        class="btn btn-ghost btn-xs p-1 text-red-600 dark:text-red-400"
                        title="Delete"
                    >
                        <Trash2 size={16} />
                    </button>
                </div>
            </div>
            <div class="grid grid-cols-2 gap-2 text-sm">
                <div>
                    <span class="text-fg-muted dark:text-dark-fg-muted">User:</span>
                    {#if event.metadata?.user_id}
                        <button
                            class="ml-1 text-blue-600 dark:text-blue-400 hover:underline font-mono"
                            title="View user overview"
                            onclick={(e) => { e.stopPropagation(); if (event.metadata.user_id) onViewUser(event.metadata.user_id); }}
                        >
                            {event.metadata.user_id}
                        </button>
                    {:else}
                        <span class="ml-1 font-mono">-</span>
                    {/if}
                </div>
                <div>
                    <span class="text-fg-muted dark:text-dark-fg-muted">Service:</span>
                    <span class="ml-1 truncate inline-block max-w-[120px] align-bottom" title={event.metadata?.service_name || '-'}>
                        {event.metadata?.service_name || '-'}
                    </span>
                </div>
                <div class="col-span-2">
                    <span class="text-fg-muted dark:text-dark-fg-muted">Correlation:</span>
                    <span class="ml-1 font-mono text-xs truncate inline-block max-w-[200px] align-bottom" title={event.metadata?.correlation_id ?? '-'}>
                        {event.metadata?.correlation_id ?? '-'}
                    </span>
                </div>
            </div>
        </div>
    {/each}
</div>

{#if events.length === 0}
    <div class="empty-state">
        No events found
    </div>
{/if}
