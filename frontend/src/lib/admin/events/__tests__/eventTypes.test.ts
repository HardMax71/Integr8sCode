import { describe, it, expect } from 'vitest';
import {
  EVENT_TYPES,
  getEventTypeColor,
  getEventTypeLabel,
  hasActiveFilters,
  getActiveFilterCount,
  getActiveFilterSummary,
} from '$lib/admin/events/eventTypes';
import type { EventFilter } from '$lib/api';

const withFilter = (override: Partial<EventFilter>): EventFilter => ({ ...override });

describe('eventTypes', () => {
  describe('EVENT_TYPES', () => {
    const expectedEvents = [
      'execution_requested', 'execution_started', 'execution_completed', 'execution_failed', 'execution_timeout',
      'pod_created', 'pod_running', 'pod_succeeded', 'pod_failed', 'pod_terminated'
    ];

    it('contains all expected events', () => {
      expectedEvents.forEach(e => expect(EVENT_TYPES).toContain(e));
    });
  });

  describe('getEventTypeColor', () => {
    it.each([
      ['execution_completed', 'text-green'],
      ['pod_succeeded', 'text-green'],
      ['execution_failed', 'text-red'],
      ['execution_timeout', 'text-red'],
      ['pod_failed', 'text-red'],
      ['execution_started', 'text-blue'],
      ['pod_running', 'text-blue'],
      ['execution_requested', 'text-purple'],
      ['pod_created', 'text-indigo'],
      ['pod_terminated', 'text-orange'],
      ['unknown_event', 'text-neutral'],
    ])('%s returns %s', (eventType, expectedColor) => {
      const color = getEventTypeColor(eventType as import('$lib/api').EventType);
      expect(color).toContain(expectedColor);
      expect(color).toContain('dark:');
    });
  });

  describe('getEventTypeLabel', () => {
    it.each([
      ['execution_requested', ''],
      ['execution_completed', 'execution_completed'],
      ['pod_running', 'pod_running'],
      ['single', 'single'],
      ['a_b_c', 'a_b_c'],
    ])('%s returns %s', (input, expected) => {
      expect(getEventTypeLabel(input as import('$lib/api').EventType)).toBe(expected);
    });
  });

  describe('hasActiveFilters', () => {
    it('returns false for empty filters', () => {
      expect(hasActiveFilters({})).toBe(false);
    });

    it.each([
      ['event_types', { event_types: ['execution_completed'] }],
      ['search_text', { search_text: 'test' }],
      ['aggregate_id', { aggregate_id: 'exec-1' }],
      ['user_id', { user_id: 'user-1' }],
      ['service_name', { service_name: 'svc' }],
      ['start_time', { start_time: '2024-01-01' }],
      ['end_time', { end_time: '2024-01-02' }],
    ])('returns true when %s has value', (_, override) => {
      expect(hasActiveFilters(withFilter(override as Partial<EventFilter>))).toBe(true);
    });
  });

  describe('getActiveFilterCount', () => {
    it.each([
      [{}, 0],
      [withFilter({ event_types: ['x' as import('$lib/api').EventType], search_text: 'y' }), 2],
      [withFilter({
        event_types: ['x' as import('$lib/api').EventType], search_text: 'y',
        aggregate_id: 'a', user_id: 'u', service_name: 's',
        start_time: 't1', end_time: 't2'
      }), 7],
    ])('returns correct count', (filters, expected) => {
      expect(getActiveFilterCount(filters)).toBe(expected);
    });
  });

  describe('getActiveFilterSummary', () => {
    it('returns empty array for empty filters', () => {
      expect(getActiveFilterSummary({})).toEqual([]);
    });

    it.each([
      [{ event_types: ['a', 'b'] }, '2 event types'],
      [{ event_types: ['a'] }, '1 event type'],
      [{ search_text: 'test' }, 'search'],
      [{ start_time: '2024-01-01' }, 'time range'],
      [{ end_time: '2024-01-02' }, 'time range'],
    ])('includes expected label', (override, expected) => {
      expect(getActiveFilterSummary(withFilter(override as Partial<EventFilter>))).toContain(expected);
    });

    it('includes all active filter labels', () => {
      const summary = getActiveFilterSummary(withFilter({
        event_types: ['x' as import('$lib/api').EventType], search_text: 'y',
        aggregate_id: 'a', user_id: 'u', service_name: 's', start_time: 't'
      }));
      ['1 event type', 'search', 'aggregate', 'user', 'service', 'time range']
        .forEach(label => expect(summary).toContain(label));
    });
  });
});
