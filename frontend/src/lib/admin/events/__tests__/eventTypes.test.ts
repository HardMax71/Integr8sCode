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
} from '../eventTypes';

describe('eventTypes', () => {
  describe('EVENT_TYPES', () => {
    it('contains execution events', () => {
      expect(EVENT_TYPES).toContain('execution.requested');
      expect(EVENT_TYPES).toContain('execution.started');
      expect(EVENT_TYPES).toContain('execution.completed');
      expect(EVENT_TYPES).toContain('execution.failed');
      expect(EVENT_TYPES).toContain('execution.timeout');
    });

    it('contains pod events', () => {
      expect(EVENT_TYPES).toContain('pod.created');
      expect(EVENT_TYPES).toContain('pod.running');
      expect(EVENT_TYPES).toContain('pod.succeeded');
      expect(EVENT_TYPES).toContain('pod.failed');
      expect(EVENT_TYPES).toContain('pod.terminated');
    });
  });

  describe('getEventTypeColor', () => {
    it('returns green for completed/succeeded events', () => {
      expect(getEventTypeColor('execution.completed')).toContain('text-green');
      expect(getEventTypeColor('pod.succeeded')).toContain('text-green');
    });

    it('returns red for failed/timeout events', () => {
      expect(getEventTypeColor('execution.failed')).toContain('text-red');
      expect(getEventTypeColor('execution.timeout')).toContain('text-red');
      expect(getEventTypeColor('pod.failed')).toContain('text-red');
    });

    it('returns blue for started/running events', () => {
      expect(getEventTypeColor('execution.started')).toContain('text-blue');
      expect(getEventTypeColor('pod.running')).toContain('text-blue');
    });

    it('returns purple for requested events', () => {
      expect(getEventTypeColor('execution.requested')).toContain('text-purple');
    });

    it('returns indigo for created events', () => {
      expect(getEventTypeColor('pod.created')).toContain('text-indigo');
    });

    it('returns orange for terminated events', () => {
      expect(getEventTypeColor('pod.terminated')).toContain('text-orange');
    });

    it('returns neutral for unknown events', () => {
      expect(getEventTypeColor('unknown.event')).toContain('text-neutral');
    });

    it('includes dark mode variants', () => {
      expect(getEventTypeColor('execution.completed')).toContain('dark:');
    });
  });

  describe('getEventTypeLabel', () => {
    it('returns empty string for execution.requested', () => {
      expect(getEventTypeLabel('execution.requested')).toBe('');
    });

    it('returns formatted label for two-part event types', () => {
      expect(getEventTypeLabel('execution.completed')).toBe('execution.completed');
      expect(getEventTypeLabel('pod.running')).toBe('pod.running');
    });

    it('returns original string for other formats', () => {
      expect(getEventTypeLabel('single')).toBe('single');
      expect(getEventTypeLabel('a.b.c')).toBe('a.b.c');
    });
  });

  describe('createDefaultEventFilters', () => {
    it('returns object with all empty values', () => {
      const filters = createDefaultEventFilters();
      expect(filters.event_types).toEqual([]);
      expect(filters.aggregate_id).toBe('');
      expect(filters.correlation_id).toBe('');
      expect(filters.user_id).toBe('');
      expect(filters.service_name).toBe('');
      expect(filters.search_text).toBe('');
      expect(filters.start_time).toBe('');
      expect(filters.end_time).toBe('');
    });

    it('returns new object each time', () => {
      const a = createDefaultEventFilters();
      const b = createDefaultEventFilters();
      expect(a).not.toBe(b);
    });
  });

  describe('hasActiveFilters', () => {
    it('returns false for empty filters', () => {
      expect(hasActiveFilters(createDefaultEventFilters())).toBe(false);
    });

    it('returns true when event_types has values', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), event_types: ['execution.completed'] };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when search_text has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), search_text: 'test' };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when correlation_id has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), correlation_id: 'abc' };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when aggregate_id has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), aggregate_id: 'exec-1' };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when user_id has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), user_id: 'user-1' };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when service_name has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), service_name: 'execution-service' };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when start_time has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), start_time: '2024-01-01' };
      expect(hasActiveFilters(filters)).toBe(true);
    });

    it('returns true when end_time has value', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), end_time: '2024-01-02' };
      expect(hasActiveFilters(filters)).toBe(true);
    });
  });

  describe('getActiveFilterCount', () => {
    it('returns 0 for empty filters', () => {
      expect(getActiveFilterCount(createDefaultEventFilters())).toBe(0);
    });

    it('counts each active filter', () => {
      const filters: EventFilters = {
        event_types: ['execution.completed'],
        search_text: 'test',
        correlation_id: 'abc',
        aggregate_id: '',
        user_id: '',
        service_name: '',
        start_time: '',
        end_time: ''
      };
      expect(getActiveFilterCount(filters)).toBe(3);
    });

    it('counts all filters when all active', () => {
      const filters: EventFilters = {
        event_types: ['execution.completed'],
        search_text: 'test',
        correlation_id: 'abc',
        aggregate_id: 'exec-1',
        user_id: 'user-1',
        service_name: 'svc',
        start_time: '2024-01-01',
        end_time: '2024-01-02'
      };
      expect(getActiveFilterCount(filters)).toBe(8);
    });
  });

  describe('getActiveFilterSummary', () => {
    it('returns empty array for empty filters', () => {
      expect(getActiveFilterSummary(createDefaultEventFilters())).toEqual([]);
    });

    it('includes event types with count', () => {
      const filters: EventFilters = {
        ...createDefaultEventFilters(),
        event_types: ['execution.completed', 'pod.running']
      };
      expect(getActiveFilterSummary(filters)).toContain('2 event types');
    });

    it('uses singular for single event type', () => {
      const filters: EventFilters = {
        ...createDefaultEventFilters(),
        event_types: ['execution.completed']
      };
      expect(getActiveFilterSummary(filters)).toContain('1 event type');
    });

    it('includes search', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), search_text: 'test' };
      expect(getActiveFilterSummary(filters)).toContain('search');
    });

    it('includes correlation', () => {
      const filters: EventFilters = { ...createDefaultEventFilters(), correlation_id: 'abc' };
      expect(getActiveFilterSummary(filters)).toContain('correlation');
    });

    it('includes time range for start or end time', () => {
      const filters1: EventFilters = { ...createDefaultEventFilters(), start_time: '2024-01-01' };
      expect(getActiveFilterSummary(filters1)).toContain('time range');

      const filters2: EventFilters = { ...createDefaultEventFilters(), end_time: '2024-01-02' };
      expect(getActiveFilterSummary(filters2)).toContain('time range');
    });

    it('includes all active filter labels', () => {
      const filters: EventFilters = {
        event_types: ['execution.completed'],
        search_text: 'test',
        correlation_id: 'abc',
        aggregate_id: 'exec-1',
        user_id: 'user-1',
        service_name: 'svc',
        start_time: '2024-01-01',
        end_time: ''
      };
      const summary = getActiveFilterSummary(filters);
      expect(summary).toContain('1 event type');
      expect(summary).toContain('search');
      expect(summary).toContain('correlation');
      expect(summary).toContain('aggregate');
      expect(summary).toContain('user');
      expect(summary).toContain('service');
      expect(summary).toContain('time range');
    });
  });
});
