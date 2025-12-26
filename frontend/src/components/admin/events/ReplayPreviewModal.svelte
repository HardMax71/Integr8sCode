<script lang="ts">
    import { AlertTriangle } from '@lucide/svelte';
    import type { EventResponse } from '$lib/api';
    import { formatTimestamp } from '$lib/formatters';
    import Modal from '$components/Modal.svelte';

    interface ReplayPreview {
        eventId: string;
        total_events: number;
        events_preview?: EventResponse[];
    }

    interface Props {
        preview: ReplayPreview | null;
        open: boolean;
        onClose: () => void;
        onConfirm: (eventId: string) => void;
    }

    let { preview, open, onClose, onConfirm }: Props = $props();

    function handleConfirm(): void {
        if (preview) {
            onClose();
            onConfirm(preview.eventId);
        }
    }
</script>

<Modal {open} title="Replay Preview" {onClose} size="md">
    {#if preview}
        <p class="text-sm text-neutral-500 dark:text-neutral-400 -mt-2 mb-4">
            Review the events that will be replayed
        </p>

        <div class="mb-4">
            <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                <div class="flex items-center justify-between">
                    <span class="font-semibold text-blue-900 dark:text-blue-100">
                        {preview.total_events} event{preview.total_events !== 1 ? 's' : ''} will be replayed
                    </span>
                    <span class="text-sm text-blue-700 dark:text-blue-300">Dry Run</span>
                </div>
            </div>
        </div>

        {#if preview.events_preview && preview.events_preview.length > 0}
            <div class="space-y-3">
                <h3 class="font-medium text-fg-default dark:text-dark-fg-default mb-2">Events to Replay:</h3>
                {#each preview.events_preview as event}
                    <div class="bg-neutral-50 dark:bg-neutral-800 rounded-lg p-3">
                        <div class="flex justify-between items-start">
                            <div>
                                <div class="font-mono text-xs text-neutral-500 dark:text-neutral-400 mb-1">{event.event_id}</div>
                                <div class="font-medium text-fg-default dark:text-dark-fg-default">{event.event_type}</div>
                                {#if event.aggregate_id}
                                    <div class="text-sm text-neutral-500 dark:text-neutral-400 mt-1">Aggregate: {event.aggregate_id}</div>
                                {/if}
                            </div>
                            <div class="text-sm text-neutral-500 dark:text-neutral-400">{formatTimestamp(event.timestamp)}</div>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}

        <div class="mt-6 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
            <div class="flex">
                <AlertTriangle size={20} class="text-yellow-400 dark:text-yellow-300 mt-0.5 shrink-0" />
                <div class="ml-3">
                    <h3 class="text-sm font-medium text-yellow-800 dark:text-yellow-200">Warning</h3>
                    <div class="mt-1 text-sm text-yellow-700 dark:text-yellow-300">
                        Replaying events will re-process them through the system. This may trigger new executions
                        and create duplicate results if the events have already been processed.
                    </div>
                </div>
            </div>
        </div>
    {/if}

    {#snippet footer()}
        <button onclick={handleConfirm} class="btn btn-primary">
            Proceed with Replay
        </button>
        <button onclick={onClose} class="btn btn-secondary-outline">
            Cancel
        </button>
    {/snippet}
</Modal>
