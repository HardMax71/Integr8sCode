<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { getEventDetailApiV1AdminEventsEventIdGetOptions } from '#lib/api/index.ts';
    import { fieldTitle, formatTimestamp } from '#lib/formatters.ts';
    import { getEventTypeColor } from '#lib/admin/events/index.ts';
    import Modal from '#components/Modal.svelte';
    import EventTypeIcon from '#components/EventTypeIcon.svelte';

    interface Props {
        eventId: string;
        onClose: () => void;
        onReplay: (eventId: string) => void;
        onViewRelated: (eventId: string) => void;
    }

    let { eventId, onClose, onReplay, onViewRelated }: Props = $props();

    const details = createQuery(() => getEventDetailApiV1AdminEventsEventIdGetOptions({ path: { event_id: eventId } }));

    // A failed load already showed the interceptor's toast, so the modal closes instead of staying empty
    $effect(() => {
        if (details.isError) onClose();
    });
    const eventData = $derived(details.data?.event);
    const relatedEvents = $derived(details.data?.related_events ?? []);
</script>

<Modal open title="Event Details" {onClose} size="lg">
    {#if eventData}
        <div class="space-y-4">
            <div>
                <h4 class="font-semibold mb-2">Basic Information</h4>
                <dl
                    class="grid grid-cols-[auto_1fr] text-fg-default dark:text-dark-fg-default *:px-4 *:py-2 *:border-b *:border-border-default dark:*:border-dark-border-default [&>dt]:font-semibold"
                >
                    <dt>{fieldTitle('event_id')}</dt>
                    <dd class="font-mono text-sm">{eventData.event_id}</dd>
                    <dt>{fieldTitle('event_type')}</dt>
                    <dd>
                        <div class="flex items-center gap-2">
                            <span
                                class="{getEventTypeColor(eventData.event_type)} shrink-0"
                                title={eventData.event_type}
                            >
                                <EventTypeIcon eventType={eventData.event_type} />
                            </span>
                            <span class={getEventTypeColor(eventData.event_type)}>
                                {eventData.event_type}
                            </span>
                        </div>
                    </dd>
                    <dt>{fieldTitle('timestamp')}</dt>
                    <dd class="text-sm">{formatTimestamp(eventData.timestamp)}</dd>
                    <dt>{fieldTitle('aggregate_id')}</dt>
                    <dd class="font-mono text-sm">{eventData.aggregate_id || '-'}</dd>
                </dl>
            </div>

            <div>
                <h4 class="font-semibold mb-2">{fieldTitle('event')}</h4>
                <pre
                    class="bg-neutral-100 dark:bg-neutral-800 p-3 rounded overflow-auto text-sm font-mono text-fg-default dark:text-dark-fg-default max-h-96">{JSON.stringify(
                        eventData,
                        null,
                        2,
                    )}</pre>
            </div>

            {#if relatedEvents.length > 0}
                <div>
                    <h4 class="font-semibold mb-2">{fieldTitle('related_events')}</h4>
                    <div class="space-y-1">
                        {#each relatedEvents as related (related.event_id)}
                            <button
                                type="button"
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
            type="button"
            onclick={() => {
                const id = eventData?.event_id;
                if (id) onReplay(id);
            }}
            class="btn btn-primary"
        >
            Replay Event
        </button>
        <button type="button" onclick={onClose} class="btn btn-secondary-outline"> Close </button>
    {/snippet}
</Modal>
