import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { appError } from '../errorStore';

describe('errorStore', () => {
  beforeEach(() => {
    // Clear the store before each test
    appError.clear();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('has null error initially', () => {
      expect(get(appError)).toBe(null);
    });
  });

  describe('setError', () => {
    it('sets an Error object', () => {
      const error = new Error('Test error message');
      appError.setError(error);

      const current = get(appError);
      expect(current).not.toBe(null);
      expect(current?.error).toBe(error);
      expect(current?.timestamp).toBeDefined();
      expect(current?.title).toBeUndefined();
    });

    it('sets a string error', () => {
      appError.setError('String error message');

      const current = get(appError);
      expect(current).not.toBe(null);
      expect(current?.error).toBe('String error message');
    });

    it('sets error with title', () => {
      appError.setError('Error with title', 'Custom Title');

      const current = get(appError);
      expect(current).not.toBe(null);
      expect(current?.error).toBe('Error with title');
      expect(current?.title).toBe('Custom Title');
    });

    it('logs error to console', () => {
      const consoleSpy = vi.spyOn(console, 'error');
      appError.setError('Logged error', 'Error Title');

      expect(consoleSpy).toHaveBeenCalledWith('[ErrorStore]', 'Error Title', 'Logged error');
    });

    it('uses default title in log when not provided', () => {
      const consoleSpy = vi.spyOn(console, 'error');
      appError.setError('Logged error without title');

      expect(consoleSpy).toHaveBeenCalledWith('[ErrorStore]', 'Error:', 'Logged error without title');
    });

    it('includes timestamp', () => {
      const before = Date.now();
      appError.setError('Timestamped error');
      const after = Date.now();

      const current = get(appError);
      expect(current?.timestamp).toBeGreaterThanOrEqual(before);
      expect(current?.timestamp).toBeLessThanOrEqual(after);
    });

    it('overwrites previous error', () => {
      appError.setError('First error');
      appError.setError('Second error');

      const current = get(appError);
      expect(current?.error).toBe('Second error');
    });
  });

  describe('clear', () => {
    it('clears the error', () => {
      appError.setError('Error to clear');
      expect(get(appError)).not.toBe(null);

      appError.clear();
      expect(get(appError)).toBe(null);
    });

    it('does nothing when already null', () => {
      appError.clear();
      expect(get(appError)).toBe(null);
    });
  });

  describe('subscribe', () => {
    it('allows subscription to store changes', () => {
      const values: (typeof appError extends { subscribe: (fn: (v: infer T) => void) => void } ? T : never)[] = [];
      const unsubscribe = appError.subscribe((value) => {
        values.push(value);
      });

      appError.setError('First');
      appError.setError('Second');
      appError.clear();

      unsubscribe();

      expect(values).toHaveLength(4); // initial null + 2 errors + clear
      expect(values[0]).toBe(null);
      expect(values[1]?.error).toBe('First');
      expect(values[2]?.error).toBe('Second');
      expect(values[3]).toBe(null);
    });
  });
});
