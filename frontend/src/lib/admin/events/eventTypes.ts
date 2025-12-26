/**
 * Event type configurations and utilities
 */

// Available event types for filtering
export const EVENT_TYPES = [
    'execution.requested',
    'execution.started',
    'execution.completed',
    'execution.failed',
    'execution.timeout',
    'pod.created',
    'pod.running',
    'pod.succeeded',
    'pod.failed',
    'pod.terminated'
] as const;

export type EventType = typeof EVENT_TYPES[number];

// Event type color mapping
export function getEventTypeColor(eventType: string): string {
    if (eventType.includes('.completed') || eventType.includes('.succeeded')) {
        return 'text-green-600 dark:text-green-400';
    }
    if (eventType.includes('.failed') || eventType.includes('.timeout')) {
        return 'text-red-600 dark:text-red-400';
    }
    if (eventType.includes('.started') || eventType.includes('.running')) {
        return 'text-blue-600 dark:text-blue-400';
    }
    if (eventType.includes('.requested')) {
        return 'text-purple-600 dark:text-purple-400';
    }
    if (eventType.includes('.created')) {
        return 'text-indigo-600 dark:text-indigo-400';
    }
    if (eventType.includes('.terminated')) {
        return 'text-orange-600 dark:text-orange-400';
    }
    return 'text-neutral-600 dark:text-neutral-400';
}

// Get display label for event type
export function getEventTypeLabel(eventType: string): string {
    // For execution.requested, show icon only (with tooltip)
    if (eventType === 'execution.requested') {
        return '';
    }

    // For all other events, show full name
    const parts = eventType.split('.');
    if (parts.length === 2) {
        return `${parts[0]}.${parts[1]}`;
    }
    return eventType;
}

// Default filter state for events
export interface EventFilters {
    event_types: string[];
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
