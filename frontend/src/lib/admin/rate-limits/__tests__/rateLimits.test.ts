import { describe, it, expect } from 'vitest';
import {
  GROUP_COLORS,
  getGroupColor,
  ENDPOINT_GROUP_PATTERNS,
  detectGroupFromEndpoint,
  createEmptyRule
} from '$lib/admin/rate-limits/rateLimits';

const EXPECTED_GROUPS = ['execution', 'admin', 'sse', 'websocket', 'auth', 'api', 'public'];

describe('rateLimits', () => {
  describe('GROUP_COLORS', () => {
    it('has all expected groups with dark mode', () => {
      EXPECTED_GROUPS.forEach(group => {
        expect(GROUP_COLORS[group]).toBeDefined();
        expect(GROUP_COLORS[group]).toContain('dark:');
      });
    });
  });

  describe('getGroupColor', () => {
    it.each([
      ['execution', GROUP_COLORS.execution],
      ['admin', GROUP_COLORS.admin],
      ['api', GROUP_COLORS.api],
    ] as const)('returns correct color for %s', (group, expected) => {
      expect(getGroupColor(group)).toBe(expected);
    });
  });

  describe('ENDPOINT_GROUP_PATTERNS', () => {
    it('has patterns for common endpoints', () => {
      expect(ENDPOINT_GROUP_PATTERNS.length).toBeGreaterThan(0);
      const groups = ENDPOINT_GROUP_PATTERNS.map(p => p.group);
      ['execution', 'admin', 'auth'].forEach(g => expect(groups).toContain(g));
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
