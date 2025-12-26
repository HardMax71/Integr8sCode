<script lang="ts">
    import type { EventDetailResponse } from '../../../lib/api';
    import { formatTimestamp } from '../../../lib/formatters';
    import { getEventTypeColor } from '../../../lib/admin/events';
    import Modal from '../../Modal.svelte';
    import EventTypeIcon from '../../EventTypeIcon.svelte';

    interface Props {
        event: EventDetailResponse | null;
        open: boolean;
        onClose: () => void;
        onReplay: (eventId: string) => void;
        onViewRelated: (eventId: string) => void;
    }

    let { event, open, onClose, onReplay, onViewRelated }: Props = $props();
</script>

<Modal {open} title="Event Details" {onClose} size="lg">
    {#if event}
        <div class="space-y-4">
            <div>
                <h4 class="font-semibold mb-2">Basic Information</h4>
                <table class="w-full">
                    <tbody>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Event ID</td>
                            <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{event.event.event_id}</td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Event Type</td>
                            <td class="px-4 py-2">
                                <div class="flex items-center gap-2">
                                    <span class="{getEventTypeColor(event.event.event_type)} shrink-0" title={event.event.event_type}>
                                        <EventTypeIcon eventType={event.event.event_type} />
                                    </span>
                                    <span class={getEventTypeColor(event.event.event_type)}>
                                        {event.event.event_type}
                                    </span>
                                </div>
                            </td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Timestamp</td>
                            <td class="px-4 py-2 text-sm text-fg-default dark:text-dark-fg-default">{formatTimestamp(event.event.timestamp)}</td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Correlation ID</td>
                            <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{event.event.correlation_id}</td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Aggregate ID</td>
                            <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{event.event.aggregate_id || '-'}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div>
                <h4 class="font-semibold mb-2">Metadata</h4>
                <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default">{JSON.stringify(event.event.metadata, null, 2)}</pre>
            </div>

            <div>
                <h4 class="font-semibold mb-2">Payload</h4>
                <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default">{JSON.stringify(event.event.payload, null, 2)}</pre>
            </div>

            {#if event.related_events && event.related_events.length > 0}
                <div>
                    <h4 class="font-semibold mb-2">Related Events</h4>
                    <div class="space-y-1">
                        {#each event.related_events as related}
                            <button
                                onclick={() => onViewRelated(related.event_id)}
                                class="flex justify-between items-center w-full p-2 bg-neutral-100 dark:bg-neutral-800 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors"
                            >
                                <span class={getEventTypeColor(related.event_type)}>
                                    {related.event_type}
                                </span>
                                <span class="text-sm text-fg-muted dark:text-dark-fg-muted">
                                    {formatTimestamp(related.timestamp)}
                                </span>
                            </button>
                        {/each}
                    </div>
                </div>
            {/if}
        </div>
    {/if}

    {#snippet footer()}
        <button
            onclick={() => event && onReplay(event.event.event_id)}
            class="btn btn-primary"
        >
            Replay Event
        </button>
        <button onclick={onClose} class="btn btn-secondary-outline">
            Close
        </button>
    {/snippet}
</Modal>
