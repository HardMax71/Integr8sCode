import { describe, it, expect } from 'vitest';
import {
  STATS_BG_COLORS,
  STATS_TEXT_COLORS,
} from '$lib/admin/constants';

describe('admin constants', () => {
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

});
