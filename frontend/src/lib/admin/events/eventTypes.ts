/**
 * Event type configurations and utilities
 */
import { EventType, zEventFilter, type EventFilter } from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';

// Re-export EventType from generated types
export type { EventType } from '#lib/api/index.ts';

// Every event type, for the filter UI
export const EVENT_TYPES: EventType[] = Object.values(EventType);

// Event type color mapping
export function getEventTypeColor(eventType: EventType): string {
    if (eventType.includes('_completed') || eventType.includes('_succeeded')) {
        return 'text-success';
    }
    if (eventType.includes('_failed') || eventType.includes('_timeout')) {
        return 'text-danger';
    }
    if (eventType.includes('_started') || eventType.includes('_running')) {
        return 'text-info';
    }
    if (eventType.includes('_requested')) {
        return 'text-purple';
    }
    if (eventType.includes('_created')) {
        return 'text-indigo';
    }
    if (eventType.includes('_terminated')) {
        return 'text-orange';
    }
    return 'text-fg-muted';
}

const FILTER_KEYS = Object.keys(zEventFilter.shape) as (keyof EventFilter)[];

function activeFilterKeys(filters: EventFilter): (keyof EventFilter)[] {
    return FILTER_KEYS.filter((key) => {
        const value = filters[key];
        return Array.isArray(value) ? value.length > 0 : !!value;
    });
}

export function hasActiveFilters(filters: EventFilter): boolean {
    return activeFilterKeys(filters).length > 0;
}

export function getActiveFilterCount(filters: EventFilter): number {
    return activeFilterKeys(filters).length;
}

export function getActiveFilterSummary(filters: EventFilter): string[] {
    return activeFilterKeys(filters).map(fieldTitle);
}
