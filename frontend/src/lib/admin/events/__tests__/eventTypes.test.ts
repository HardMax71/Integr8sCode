import { describe, it, expect } from 'vitest';
import {
  EVENT_TYPES,
  getEventTypeColor,
  getEventTypeLabel,
  createDefaultEventFilters,
  hasActiveFilters,
  getActiveFilterCount,
  getActiveFilterSummary,
  type EventFilters
} from '$lib/admin/events/eventTypes';

const withFilter = (override: Partial<EventFilters>): EventFilters =>
  ({ ...createDefaultEventFilters(), ...override });

describe('eventTypes', () => {
  describe('EVENT_TYPES', () => {
    const expectedEvents = [
      'execution.requested', 'execution.started', 'execution.completed', 'execution.failed', 'execution.timeout',
      'pod.created', 'pod.running', 'pod.succeeded', 'pod.failed', 'pod.terminated'
    ];

    it('contains all expected events', () => {
      expectedEvents.forEach(e => expect(EVENT_TYPES).toContain(e));
    });
  });

  describe('getEventTypeColor', () => {
    it.each([
      ['execution.completed', 'text-green'],
      ['pod.succeeded', 'text-green'],
      ['execution.failed', 'text-red'],
      ['execution.timeout', 'text-red'],
      ['pod.failed', 'text-red'],
      ['execution.started', 'text-blue'],
      ['pod.running', 'text-blue'],
      ['execution.requested', 'text-purple'],
      ['pod.created', 'text-indigo'],
      ['pod.terminated', 'text-orange'],
      ['unknown.event', 'text-neutral'],
    ])('%s returns %s', (eventType, expectedColor) => {
      const color = getEventTypeColor(eventType);
      expect(color).toContain(expectedColor);
      expect(color).toContain('dark:');
    });
  });

  describe('getEventTypeLabel', () => {
    it.each([
      ['execution.requested', ''],
      ['execution.completed', 'execution.completed'],
      ['pod.running', 'pod.running'],
      ['single', 'single'],
      ['a.b.c', 'a.b.c'],
    ])('%s returns %s', (input, expected) => {
      expect(getEventTypeLabel(input)).toBe(expected);
    });
  });

  describe('createDefaultEventFilters', () => {
    it('returns object with all empty values', () => {
      expect(createDefaultEventFilters()).toEqual({
        event_types: [],
        aggregate_id: '',
        correlation_id: '',
        user_id: '',
        service_name: '',
        search_text: '',
        start_time: '',
        end_time: ''
      });
    });

    it('returns new object each time', () => {
      expect(createDefaultEventFilters()).not.toBe(createDefaultEventFilters());
    });
  });

  describe('hasActiveFilters', () => {
    it('returns false for empty filters', () => {
      expect(hasActiveFilters(createDefaultEventFilters())).toBe(false);
    });

    it.each([
      ['event_types', { event_types: ['execution.completed'] }],
      ['search_text', { search_text: 'test' }],
      ['correlation_id', { correlation_id: 'abc' }],
      ['aggregate_id', { aggregate_id: 'exec-1' }],
      ['user_id', { user_id: 'user-1' }],
      ['service_name', { service_name: 'svc' }],
      ['start_time', { start_time: '2024-01-01' }],
      ['end_time', { end_time: '2024-01-02' }],
    ])('returns true when %s has value', (_, override) => {
      expect(hasActiveFilters(withFilter(override as Partial<EventFilters>))).toBe(true);
    });
  });

  describe('getActiveFilterCount', () => {
    it.each([
      [createDefaultEventFilters(), 0],
      [withFilter({ event_types: ['x'], search_text: 'y', correlation_id: 'z' }), 3],
      [withFilter({
        event_types: ['x'], search_text: 'y', correlation_id: 'z',
        aggregate_id: 'a', user_id: 'u', service_name: 's',
        start_time: 't1', end_time: 't2'
      }), 8],
    ])('returns correct count', (filters, expected) => {
      expect(getActiveFilterCount(filters)).toBe(expected);
    });
  });

  describe('getActiveFilterSummary', () => {
    it('returns empty array for empty filters', () => {
      expect(getActiveFilterSummary(createDefaultEventFilters())).toEqual([]);
    });

    it.each([
      [{ event_types: ['a', 'b'] }, '2 event types'],
      [{ event_types: ['a'] }, '1 event type'],
      [{ search_text: 'test' }, 'search'],
      [{ correlation_id: 'abc' }, 'correlation'],
      [{ start_time: '2024-01-01' }, 'time range'],
      [{ end_time: '2024-01-02' }, 'time range'],
    ])('includes expected label', (override, expected) => {
      expect(getActiveFilterSummary(withFilter(override as Partial<EventFilters>))).toContain(expected);
    });

    it('includes all active filter labels', () => {
      const summary = getActiveFilterSummary(withFilter({
        event_types: ['x'], search_text: 'y', correlation_id: 'z',
        aggregate_id: 'a', user_id: 'u', service_name: 's', start_time: 't'
      }));
      ['1 event type', 'search', 'correlation', 'aggregate', 'user', 'service', 'time range']
        .forEach(label => expect(summary).toContain(label));
    });
  });
});
