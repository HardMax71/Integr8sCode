/**
 * Event type configurations and utilities
 */
import type { EventType } from '$lib/api';

// Re-export EventType from generated types
export type { EventType } from '$lib/api';

// Common event types for filtering UI (subset of all EventType values)
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
export function getEventTypeColor(eventType: string): string {
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
export function getEventTypeLabel(eventType: string): string {
    // For execution_requested, show icon only (with tooltip)
    if (eventType === 'execution_requested') {
        return '';
    }

    // Return the event type as-is (already readable with underscores)
    return eventType;
}

// Default filter state for events
export interface EventFilters {
    event_types: EventType[];
    aggregate_id: string;
    correlation_id: string;
    user_id: string;
    service_name: string;
    search_text: string;
    start_time: string;
    end_time: string;
}

export function createDefaultEventFilters(): EventFilters {
    return {
        event_types: [],
        aggregate_id: '',
        correlation_id: '',
        user_id: '',
        service_name: '',
        search_text: '',
        start_time: '',
        end_time: ''
    };
}

export function hasActiveFilters(filters: EventFilters): boolean {
    return (
        filters.event_types.length > 0 ||
        !!filters.search_text ||
        !!filters.correlation_id ||
        !!filters.aggregate_id ||
        !!filters.user_id ||
        !!filters.service_name ||
        !!filters.start_time ||
        !!filters.end_time
    );
}

export function getActiveFilterCount(filters: EventFilters): number {
    let count = 0;
    if (filters.event_types.length > 0) count++;
    if (filters.search_text) count++;
    if (filters.correlation_id) count++;
    if (filters.aggregate_id) count++;
    if (filters.user_id) count++;
    if (filters.service_name) count++;
    if (filters.start_time) count++;
    if (filters.end_time) count++;
    return count;
}

export function getActiveFilterSummary(filters: EventFilters): string[] {
    const items: string[] = [];
    if (filters.event_types.length > 0) {
        items.push(`${filters.event_types.length} event type${filters.event_types.length > 1 ? 's' : ''}`);
    }
    if (filters.search_text) items.push('search');
    if (filters.correlation_id) items.push('correlation');
    if (filters.aggregate_id) items.push('aggregate');
    if (filters.user_id) items.push('user');
    if (filters.service_name) items.push('service');
    if (filters.start_time || filters.end_time) items.push('time range');
    return items;
}
