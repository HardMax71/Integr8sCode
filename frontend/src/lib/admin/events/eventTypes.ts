/**
 * Event type configurations and utilities
 */
import type { EventFilter, EventType } from '$lib/api';

// Re-export EventType from generated types
export type { EventType } from '$lib/api';

// Common event types for filtering UI (manually curated subset of all EventType values).
// Keep in sync with EventType in types.gen.ts when adding new event types to the backend.
export const EVENT_TYPES: EventType[] = [
    'execution_requested',
    'execution_started',
    'execution_completed',
    'execution_failed',
    'execution_timeout',
    'pod_created',
    'pod_running',
    'pod_succeeded',
    'pod_failed',
    'pod_terminated'
];

// Event type color mapping
export function getEventTypeColor(eventType: EventType): string {
    if (eventType.includes('_completed') || eventType.includes('_succeeded')) {
        return 'text-green-600 dark:text-green-400';
    }
    if (eventType.includes('_failed') || eventType.includes('_timeout')) {
        return 'text-red-600 dark:text-red-400';
    }
    if (eventType.includes('_started') || eventType.includes('_running')) {
        return 'text-blue-600 dark:text-blue-400';
    }
    if (eventType.includes('_requested')) {
        return 'text-purple-600 dark:text-purple-400';
    }
    if (eventType.includes('_created')) {
        return 'text-indigo-600 dark:text-indigo-400';
    }
    if (eventType.includes('_terminated')) {
        return 'text-orange-600 dark:text-orange-400';
    }
    return 'text-neutral-600 dark:text-neutral-400';
}

// Get display label for event type
export function getEventTypeLabel(eventType: EventType): string {
    // For execution_requested, show icon only (with tooltip)
    if (eventType === 'execution_requested') {
        return '';
    }

    // Return the event type as-is (already readable with underscores)
    return eventType;
}

export function hasActiveFilters(filters: EventFilter): boolean {
    return (
        (filters.event_types?.length ?? 0) > 0 ||
        !!filters.search_text ||
        !!filters.aggregate_id ||
        !!filters.user_id ||
        !!filters.service_name ||
        !!filters.start_time ||
        !!filters.end_time
    );
}

export function getActiveFilterCount(filters: EventFilter): number {
    let count = 0;
    if (filters.event_types?.length) count++;
    if (filters.search_text) count++;
    if (filters.aggregate_id) count++;
    if (filters.user_id) count++;
    if (filters.service_name) count++;
    if (filters.start_time) count++;
    if (filters.end_time) count++;
    return count;
}

export function getActiveFilterSummary(filters: EventFilter): string[] {
    const items: string[] = [];
    if (filters.event_types?.length) {
        items.push(`${filters.event_types.length} event type${filters.event_types.length > 1 ? 's' : ''}`);
    }
    if (filters.search_text) items.push('search');
    if (filters.aggregate_id) items.push('aggregate');
    if (filters.user_id) items.push('user');
    if (filters.service_name) items.push('service');
    if (filters.start_time || filters.end_time) items.push('time range');
    return items;
}
