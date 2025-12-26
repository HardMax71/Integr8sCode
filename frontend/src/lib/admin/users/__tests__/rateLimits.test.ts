import { describe, it, expect } from 'vitest';
import {
  GROUP_COLORS,
  getGroupColor,
  ENDPOINT_GROUP_PATTERNS,
  detectGroupFromEndpoint,
  getDefaultRules,
  getDefaultRulesWithMultiplier,
  createEmptyRule
} from '../rateLimits';

describe('rateLimits', () => {
  describe('GROUP_COLORS', () => {
    it('has all expected groups', () => {
      expect(GROUP_COLORS.execution).toBeDefined();
      expect(GROUP_COLORS.admin).toBeDefined();
      expect(GROUP_COLORS.sse).toBeDefined();
      expect(GROUP_COLORS.websocket).toBeDefined();
      expect(GROUP_COLORS.auth).toBeDefined();
      expect(GROUP_COLORS.api).toBeDefined();
      expect(GROUP_COLORS.public).toBeDefined();
    });

    it('includes dark mode variants', () => {
      expect(GROUP_COLORS.execution).toContain('dark:');
    });
  });

  describe('getGroupColor', () => {
    it('returns correct color for known groups', () => {
      expect(getGroupColor('execution')).toBe(GROUP_COLORS.execution);
      expect(getGroupColor('admin')).toBe(GROUP_COLORS.admin);
    });

    it('returns api color for unknown groups', () => {
      expect(getGroupColor('unknown')).toBe(GROUP_COLORS.api);
    });
  });

  describe('ENDPOINT_GROUP_PATTERNS', () => {
    it('has patterns for common endpoints', () => {
      expect(ENDPOINT_GROUP_PATTERNS.length).toBeGreaterThan(0);
      const groups = ENDPOINT_GROUP_PATTERNS.map(p => p.group);
      expect(groups).toContain('execution');
      expect(groups).toContain('admin');
      expect(groups).toContain('auth');
    });
  });

  describe('detectGroupFromEndpoint', () => {
    it('detects execution endpoints', () => {
      expect(detectGroupFromEndpoint('/api/v1/execute')).toBe('execution');
      expect(detectGroupFromEndpoint('^/api/v1/execute$')).toBe('execution');
    });

    it('detects admin endpoints', () => {
      expect(detectGroupFromEndpoint('/admin/users')).toBe('admin');
      expect(detectGroupFromEndpoint('/api/v1/admin/events')).toBe('admin');
    });

    it('detects sse/events endpoints', () => {
      expect(detectGroupFromEndpoint('/events/stream')).toBe('sse');
      expect(detectGroupFromEndpoint('/api/v1/events/123')).toBe('sse');
    });

    it('detects websocket endpoints', () => {
      expect(detectGroupFromEndpoint('/ws')).toBe('websocket');
      expect(detectGroupFromEndpoint('/api/v1/ws/connect')).toBe('websocket');
    });

    it('detects auth endpoints', () => {
      expect(detectGroupFromEndpoint('/auth/login')).toBe('auth');
      expect(detectGroupFromEndpoint('/api/v1/auth/token')).toBe('auth');
    });

    it('detects public endpoints', () => {
      expect(detectGroupFromEndpoint('/health')).toBe('public');
      expect(detectGroupFromEndpoint('/api/health/check')).toBe('public');
    });

    it('returns api for unknown endpoints', () => {
      expect(detectGroupFromEndpoint('/api/v1/users')).toBe('api');
      expect(detectGroupFromEndpoint('/some/random/path')).toBe('api');
    });

    it('handles regex patterns correctly', () => {
      expect(detectGroupFromEndpoint('^/api/v1/execute.*$')).toBe('execution');
    });
  });

  describe('getDefaultRules', () => {
    it('returns array of rules', () => {
      const rules = getDefaultRules();
      expect(Array.isArray(rules)).toBe(true);
      expect(rules.length).toBeGreaterThan(0);
    });

    it('each rule has required properties', () => {
      const rules = getDefaultRules();
      rules.forEach(rule => {
        expect(rule).toHaveProperty('endpoint_pattern');
        expect(rule).toHaveProperty('group');
        expect(rule).toHaveProperty('requests');
        expect(rule).toHaveProperty('window_seconds');
        expect(rule).toHaveProperty('algorithm');
        expect(rule).toHaveProperty('priority');
      });
    });

    it('includes execution rule with 10 req/min', () => {
      const rules = getDefaultRules();
      const execRule = rules.find(r => r.group === 'execution');
      expect(execRule).toBeDefined();
      expect(execRule?.requests).toBe(10);
    });

    it('includes api rule with 60 req/min', () => {
      const rules = getDefaultRules();
      const apiRule = rules.find(r => r.group === 'api');
      expect(apiRule).toBeDefined();
      expect(apiRule?.requests).toBe(60);
    });
  });

  describe('getDefaultRulesWithMultiplier', () => {
    it('returns rules with effective_requests', () => {
      const rules = getDefaultRulesWithMultiplier(1.0);
      rules.forEach(rule => {
        expect(rule).toHaveProperty('effective_requests');
      });
    });

    it('applies multiplier correctly', () => {
      const rules = getDefaultRulesWithMultiplier(2.0);
      const execRule = rules.find(r => r.group === 'execution');
      expect(execRule?.effective_requests).toBe(20);

      const apiRule = rules.find(r => r.group === 'api');
      expect(apiRule?.effective_requests).toBe(120);
    });

    it('handles 0.5 multiplier', () => {
      const rules = getDefaultRulesWithMultiplier(0.5);
      const execRule = rules.find(r => r.group === 'execution');
      expect(execRule?.effective_requests).toBe(5);
    });

    it('uses 1.0 as default multiplier', () => {
      const rules = getDefaultRulesWithMultiplier();
      const execRule = rules.find(r => r.group === 'execution');
      expect(execRule?.effective_requests).toBe(10);
    });

    it('handles falsy multiplier as 1.0', () => {
      const rules = getDefaultRulesWithMultiplier(0);
      const execRule = rules.find(r => r.group === 'execution');
      expect(execRule?.effective_requests).toBe(10);
    });

    it('floors non-integer results', () => {
      const rules = getDefaultRulesWithMultiplier(1.5);
      const execRule = rules.find(r => r.group === 'execution');
      expect(execRule?.effective_requests).toBe(15);

      const rules2 = getDefaultRulesWithMultiplier(1.3);
      const execRule2 = rules2.find(r => r.group === 'execution');
      expect(execRule2?.effective_requests).toBe(13);
    });
  });

  describe('createEmptyRule', () => {
    it('returns rule with default values', () => {
      const rule = createEmptyRule();
      expect(rule.endpoint_pattern).toBe('');
      expect(rule.group).toBe('api');
      expect(rule.requests).toBe(60);
      expect(rule.window_seconds).toBe(60);
      expect(rule.burst_multiplier).toBe(1.5);
      expect(rule.algorithm).toBe('sliding_window');
      expect(rule.priority).toBe(0);
      expect(rule.enabled).toBe(true);
    });

    it('returns new object each time', () => {
      const a = createEmptyRule();
      const b = createEmptyRule();
      expect(a).not.toBe(b);
    });
  });
});
