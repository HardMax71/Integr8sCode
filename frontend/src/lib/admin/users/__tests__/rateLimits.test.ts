import { describe, it, expect } from 'vitest';
import {
  GROUP_COLORS,
  getGroupColor,
  ENDPOINT_GROUP_PATTERNS,
  detectGroupFromEndpoint,
  getDefaultRules,
  getDefaultRulesWithMultiplier,
  createEmptyRule
} from '$lib/admin/users/rateLimits';

const EXPECTED_GROUPS = ['execution', 'admin', 'sse', 'websocket', 'auth', 'api', 'public'];
const findRuleByGroup = (rules: ReturnType<typeof getDefaultRules>, group: string) =>
  rules.find(r => r.group === group);

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
      ['unknown', GROUP_COLORS.api],
    ])('returns correct color for %s', (group, expected) => {
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

  describe('getDefaultRules', () => {
    const rules = getDefaultRules();

    it('returns array of rules with required properties', () => {
      expect(rules.length).toBeGreaterThan(0);
      const requiredProps = ['endpoint_pattern', 'group', 'requests', 'window_seconds', 'algorithm', 'priority'];
      rules.forEach(rule => requiredProps.forEach(prop => expect(rule).toHaveProperty(prop)));
    });

    it.each([
      ['execution', 10],
      ['api', 60],
    ])('includes %s rule with %d req/min', (group, requests) => {
      const rule = findRuleByGroup(rules, group);
      expect(rule).toBeDefined();
      expect(rule?.requests).toBe(requests);
    });
  });

  describe('getDefaultRulesWithMultiplier', () => {
    it('returns rules with effective_requests', () => {
      getDefaultRulesWithMultiplier(1.0).forEach(rule => {
        expect(rule).toHaveProperty('effective_requests');
      });
    });

    it.each([
      [2.0, 20, 120],
      [0.5, 5, 30],
      [1.0, 10, 60],
      [1.5, 15, 90],
      [1.3, 13, 78],
    ])('with multiplier %d: execution=%d, api=%d', (multiplier, execExpected, apiExpected) => {
      const rules = getDefaultRulesWithMultiplier(multiplier);
      expect(findRuleByGroup(rules, 'execution')?.effective_requests).toBe(execExpected);
      expect(findRuleByGroup(rules, 'api')?.effective_requests).toBe(apiExpected);
    });

    it('handles non-positive multipliers as 1.0', () => {
      [undefined, 0, -1, -0.5].forEach(mult => {
        const rules = getDefaultRulesWithMultiplier(mult);
        expect(findRuleByGroup(rules, 'execution')?.effective_requests).toBe(10);
      });
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
