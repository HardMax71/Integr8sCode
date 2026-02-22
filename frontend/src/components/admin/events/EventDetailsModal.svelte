<script lang="ts">
    import type { EventDetailResponse } from '$lib/api';
    import { formatTimestamp } from '$lib/formatters';
    import { getEventTypeColor } from '$lib/admin/events';
    import Modal from '$components/Modal.svelte';
    import EventTypeIcon from '$components/EventTypeIcon.svelte';

    interface Props {
        event: EventDetailResponse | null;
        open: boolean;
        onClose: () => void;
        onReplay: (eventId: string) => void;
        onViewRelated: (eventId: string) => void;
    }

    let { event, open, onClose, onReplay, onViewRelated }: Props = $props();

    // Properly typed - no casts needed, API types are now correct
    const eventData = $derived(event?.event);
    const relatedEvents = $derived(event?.related_events ?? []);
</script>

<Modal {open} title="Event Details" {onClose} size="lg">
    {#if event && eventData}
        <div class="space-y-4">
            <div>
                <h4 class="font-semibold mb-2">Basic Information</h4>
                <table class="w-full">
                    <tbody>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Event ID</td>
                            <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{eventData.event_id}</td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Event Type</td>
                            <td class="px-4 py-2">
                                <div class="flex items-center gap-2">
                                    <span class="{getEventTypeColor(eventData.event_type)} shrink-0" title={eventData.event_type}>
                                        <EventTypeIcon eventType={eventData.event_type} />
                                    </span>
                                    <span class={getEventTypeColor(eventData.event_type)}>
                                        {eventData.event_type}
                                    </span>
                                </div>
                            </td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Timestamp</td>
                            <td class="px-4 py-2 text-sm text-fg-default dark:text-dark-fg-default">{formatTimestamp(eventData.timestamp)}</td>
                        </tr>
                        <tr class="border-b border-border-default dark:border-dark-border-default">
                            <td class="px-4 py-2 font-semibold text-fg-default dark:text-dark-fg-default">Aggregate ID</td>
                            <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{eventData.aggregate_id || '-'}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div>
                <h4 class="font-semibold mb-2">Full Event Data</h4>
                <pre class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default max-h-96">{JSON.stringify(eventData, null, 2)}</pre>
            </div>

            {#if relatedEvents.length > 0}
                <div>
                    <h4 class="font-semibold mb-2">Related Events</h4>
                    <div class="space-y-1">
                        {#each relatedEvents as related}
                            <button type="button"
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
        <button type="button"
            onclick={() => {
                const id = eventData?.event_id;
                if (id) onReplay(id);
            }}
            class="btn btn-primary"
        >
            Replay Event
        </button>
        <button type="button" onclick={onClose} class="btn btn-secondary-outline">
            Close
        </button>
    {/snippet}
</Modal>
