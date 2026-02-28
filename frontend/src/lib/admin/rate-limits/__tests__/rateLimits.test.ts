import { describe, it, expect } from 'vitest';
import type { EndpointGroup } from '$lib/api';
import {
  getGroupColor,
  detectGroupFromEndpoint,
  createEmptyRule
} from '$lib/admin/rate-limits/rateLimits';

const EXPECTED_GROUPS: EndpointGroup[] = ['execution', 'admin', 'sse', 'websocket', 'auth', 'api', 'public'];

describe('rateLimits', () => {
  describe('getGroupColor', () => {
    it.each(EXPECTED_GROUPS)('returns a dark-mode color string for %s', (group) => {
      const color = getGroupColor(group);
      expect(color).toBeDefined();
      expect(color).toContain('dark:');
    });

    it.each([
      ['execution', 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200'],
      ['admin', 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'],
      ['api', 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-200'],
    ] as const)('returns correct color for %s', (group, expected) => {
      expect(getGroupColor(group)).toBe(expected);
    });
  });

  describe('detectGroupFromEndpoint', () => {
    it.each([
      ['/api/v1/execute', 'execution'],
      ['^/api/v1/execute$', 'execution'],
      ['^/api/v1/execute.*$', 'execution'],
      ['/admin/users', 'admin'],
      ['/api/v1/admin/events', 'admin'],
      ['/events/stream', 'sse'],
      ['/api/v1/events/123', 'sse'],
      ['/ws', 'websocket'],
      ['/api/v1/ws/connect', 'websocket'],
      ['/auth/login', 'auth'],
      ['/api/v1/auth/token', 'auth'],
      ['/health', 'public'],
      ['/api/health/check', 'public'],
      ['/api/v1/users', 'api'],
      ['/some/random/path', 'api'],
    ])('detects %s as %s', (endpoint, expected) => {
      expect(detectGroupFromEndpoint(endpoint)).toBe(expected);
    });
  });

  describe('createEmptyRule', () => {
    it('returns rule with expected defaults', () => {
      const rule = createEmptyRule();
      expect(rule).toEqual({
        endpoint_pattern: '',
        group: 'api',
        requests: 60,
        window_seconds: 60,
        burst_multiplier: 1.5,
        algorithm: 'sliding_window',
        priority: 0,
        enabled: true
      });
    });

    it('returns new object each time', () => {
      expect(createEmptyRule()).not.toBe(createEmptyRule());
    });
  });
});
