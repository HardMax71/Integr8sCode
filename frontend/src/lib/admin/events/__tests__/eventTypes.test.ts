import { describe, it, expect } from 'vitest';
import {
    EVENT_TYPES,
    getEventTypeColor,
    hasActiveFilters,
    getActiveFilterCount,
    getActiveFilterSummary,
} from '#lib/admin/events/eventTypes.ts';
import { EventType, type EventFilter } from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';

const ALL_FILTERS: EventFilter = {
    event_types: [EventType.EXECUTION_COMPLETED],
    search_text: 'y',
    aggregate_id: 'a',
    user_id: 'u',
    service_name: 's',
    start_time: new Date(1).toISOString(),
    end_time: new Date(2).toISOString(),
};

describe('eventTypes', () => {
    describe('EVENT_TYPES', () => {
        it('lists every generated event type', () => {
            expect(EVENT_TYPES).toEqual(Object.values(EventType));
        });
    });

    describe('getEventTypeColor', () => {
        it.each([
            [EventType.EXECUTION_COMPLETED, 'text-success'],
            [EventType.POD_SUCCEEDED, 'text-success'],
            [EventType.EXECUTION_FAILED, 'text-danger'],
            [EventType.EXECUTION_TIMEOUT, 'text-danger'],
            [EventType.POD_FAILED, 'text-danger'],
            [EventType.EXECUTION_STARTED, 'text-info'],
            [EventType.POD_RUNNING, 'text-info'],
            [EventType.EXECUTION_REQUESTED, 'text-purple'],
            [EventType.POD_CREATED, 'text-indigo'],
            [EventType.POD_TERMINATED, 'text-orange'],
            [EventType.USER_SETTINGS_UPDATED, 'text-fg-muted'],
        ])('%s returns %s', (eventType, expectedColor) => {
            expect(getEventTypeColor(eventType)).toBe(expectedColor);
        });
    });

    describe('hasActiveFilters', () => {
        it('returns false for empty filters', () => {
            expect(hasActiveFilters({})).toBe(false);
        });

        it.each(Object.entries(ALL_FILTERS))('returns true when %s has value', (key, value) => {
            expect(hasActiveFilters({ [key]: value })).toBe(true);
        });
    });

    describe('getActiveFilterCount', () => {
        it.each([
            [{}, 0],
            [{ event_types: [EventType.EXECUTION_COMPLETED], search_text: 'y' }, 2],
            [ALL_FILTERS, 7],
        ])('returns correct count', (filters, expected) => {
            expect(getActiveFilterCount(filters)).toBe(expected);
        });
    });

    describe('getActiveFilterSummary', () => {
        it('returns empty array for empty filters', () => {
            expect(getActiveFilterSummary({})).toEqual([]);
        });

        it.each([
            [{ event_types: [EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED] }, 'Event Types'],
            [{ search_text: 'test' }, 'Search Text'],
            [{ start_time: '2024-01-01T00:00:00Z' }, 'Start Time'],
            [{ end_time: '2024-01-02T00:00:00Z' }, 'End Time'],
        ])('names the active filter by its field title', (filters, expected) => {
            expect(getActiveFilterSummary(filters)).toEqual([expected]);
        });

        it('names every active filter in the order of the EventFilter schema', () => {
            expect(getActiveFilterSummary(ALL_FILTERS)).toEqual(
                ['event_types', 'aggregate_id', 'user_id', 'start_time', 'end_time', 'service_name', 'search_text'].map(
                    fieldTitle,
                ),
            );
        });

        it('skips an empty event type list', () => {
            expect(getActiveFilterSummary({ event_types: [] })).toEqual([]);
        });
    });
});
