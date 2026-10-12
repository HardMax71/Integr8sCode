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
