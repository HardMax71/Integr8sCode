<script lang="ts" module>
    import type { EventReplayResponse } from '#lib/api/index.ts';

    export type ReplayPreview = Pick<EventReplayResponse, 'total_events' | 'events_preview'> & { eventId: string };
</script>

<script lang="ts">
    import { TriangleAlert } from '@lucide/svelte';
    import { fieldTitle, formatTimestamp } from '#lib/formatters.ts';
    import Modal from '#components/Modal.svelte';

    interface Props {
        preview: ReplayPreview;
        onClose: () => void;
        onConfirm: (eventId: string) => void;
    }

    let { preview, onClose, onConfirm }: Props = $props();

    // Closing clears the preview on the page, so take the event id first
    function handleConfirm(): void {
        const { eventId } = preview;
        onClose();
        onConfirm(eventId);
    }
</script>

<Modal open title="Replay Preview" {onClose} size="md">
    <p class="text-sm text-fg-muted -mt-2 mb-4">Review the events that will be replayed</p>

    <div class="mb-4">
        <div class="bg-info-soft border border-info/30 rounded-lg p-4">
            <div class="flex items-center justify-between">
                <span class="font-semibold text-info">
                    {preview.total_events} event{preview.total_events !== 1 ? 's' : ''} will be replayed
                </span>
                <span class="text-sm text-info">{fieldTitle('dry_run')}</span>
            </div>
        </div>
    </div>

    {#if preview.events_preview && preview.events_preview.length > 0}
        <div class="space-y-3">
            <h3 class="font-medium text-fg mb-2">
                {fieldTitle('events_preview')}
            </h3>
            {#each preview.events_preview as event (event.event_id)}
                <div class="bg-muted rounded-lg p-3">
                    <div class="flex justify-between items-start">
                        <div>
                            <div class="font-mono text-xs text-fg-muted mb-1">
                                {event.event_id}
                            </div>
                            <div class="font-medium text-fg">
                                {event.event_type}
                            </div>
                            {#if event.aggregate_id}
                                <dl class="flex gap-2 text-sm text-fg-muted mt-1">
                                    <dt>{fieldTitle('aggregate_id')}</dt>
                                    <dd class="font-mono">{event.aggregate_id}</dd>
                                </dl>
                            {/if}
                        </div>
                        <div class="text-sm text-fg-muted">
                            {formatTimestamp(event.timestamp)}
                        </div>
                    </div>
                </div>
            {/each}
        </div>
    {/if}

    <div class="mt-6 bg-warning-soft border border-warning/30 rounded-lg p-4">
        <div class="flex">
            <TriangleAlert size={20} class="text-warning mt-0.5 shrink-0" />
            <div class="ml-3">
                <h3 class="text-sm font-medium text-warning">Warning</h3>
                <div class="mt-1 text-sm text-warning">
                    Replaying events will re-process them through the system. This may trigger new executions and create
                    duplicate results if the events have already been processed.
                </div>
            </div>
        </div>
    </div>

    {#snippet footer()}
        <button type="button" onclick={handleConfirm} class="btn btn-primary"> Proceed with Replay </button>
        <button type="button" onclick={onClose} class="btn btn-secondary-outline"> Cancel </button>
    {/snippet}
</Modal>
