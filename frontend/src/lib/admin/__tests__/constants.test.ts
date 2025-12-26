import { describe, it, expect } from 'vitest';
import {
  STATUS_COLORS,
  STATS_BG_COLORS,
  STATS_TEXT_COLORS,
  ROLE_COLORS,
  ACTIVE_STATUS_COLORS
} from '../constants';

describe('admin constants', () => {
  describe('STATUS_COLORS', () => {
    it('has all expected status types', () => {
      expect(STATUS_COLORS.success).toBe('badge-success');
      expect(STATUS_COLORS.error).toBe('badge-danger');
      expect(STATUS_COLORS.warning).toBe('badge-warning');
      expect(STATUS_COLORS.info).toBe('badge-info');
      expect(STATUS_COLORS.neutral).toBe('badge-neutral');
    });
  });

  describe('STATS_BG_COLORS', () => {
    it('has all expected background colors', () => {
      expect(STATS_BG_COLORS.green).toContain('bg-green');
      expect(STATS_BG_COLORS.red).toContain('bg-red');
      expect(STATS_BG_COLORS.yellow).toContain('bg-yellow');
      expect(STATS_BG_COLORS.blue).toContain('bg-blue');
      expect(STATS_BG_COLORS.purple).toContain('bg-purple');
      expect(STATS_BG_COLORS.orange).toContain('bg-orange');
      expect(STATS_BG_COLORS.neutral).toContain('bg-neutral');
    });

    it('includes dark mode variants', () => {
      expect(STATS_BG_COLORS.green).toContain('dark:bg-green');
    });
  });

  describe('STATS_TEXT_COLORS', () => {
    it('has all expected text colors', () => {
      expect(STATS_TEXT_COLORS.green).toContain('text-green');
      expect(STATS_TEXT_COLORS.red).toContain('text-red');
      expect(STATS_TEXT_COLORS.yellow).toContain('text-yellow');
      expect(STATS_TEXT_COLORS.blue).toContain('text-blue');
    });

    it('includes dark mode variants', () => {
      expect(STATS_TEXT_COLORS.green).toContain('dark:text-green');
    });
  });

  describe('ROLE_COLORS', () => {
    it('has admin and user roles', () => {
      expect(ROLE_COLORS.admin).toBe('badge-info');
      expect(ROLE_COLORS.user).toBe('badge-neutral');
    });

    it('returns undefined for unknown role', () => {
      expect(ROLE_COLORS['unknown']).toBeUndefined();
    });
  });

  describe('ACTIVE_STATUS_COLORS', () => {
    it('has active/inactive status colors', () => {
      expect(ACTIVE_STATUS_COLORS.active).toBe('badge-success');
      expect(ACTIVE_STATUS_COLORS.inactive).toBe('badge-danger');
      expect(ACTIVE_STATUS_COLORS.disabled).toBe('badge-danger');
    });
  });
});
