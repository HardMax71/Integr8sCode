import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

describe('errorStore', () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('has null error initially', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      expect(appError.current).toBe(null);
    });
  });

  describe('setError', () => {
    it('sets an Error object', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      const error = new Error('Test error message');
      appError.setError(error);

      expect(appError.current).not.toBe(null);
      expect(appError.current?.error).toBe(error);
      expect(appError.current?.title).toBeUndefined();
    });

    it('sets a string error', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      appError.setError('String error message');

      expect(appError.current).not.toBe(null);
      expect(appError.current?.error).toBe('String error message');
    });

    it('sets error with title', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      appError.setError('Error with title', 'Custom Title');

      expect(appError.current).not.toBe(null);
      expect(appError.current?.error).toBe('Error with title');
      expect(appError.current?.title).toBe('Custom Title');
    });

    it('logs error via consola', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      const consoleSpy = vi.spyOn(console, 'error');
      appError.setError('Logged error', 'Error Title');

      const args = consoleSpy.mock.calls[0]!;
      expect(args[0]).toContain('ErrorStore');
      expect(args[0]).toContain('Error Title');
      expect(args[args.length - 1]).toBe('Logged error');
    });

    it('logs error without title via consola', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      const consoleSpy = vi.spyOn(console, 'error');
      appError.setError('Logged error without title');

      const args = consoleSpy.mock.calls[0]!;
      expect(args[0]).toContain('ErrorStore');
      expect(args[0]).toContain('Error:');
      expect(args[args.length - 1]).toBe('Logged error without title');
    });

    it('overwrites previous error', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      appError.setError('First error');
      appError.setError('Second error');

      expect(appError.current?.error).toBe('Second error');
    });
  });

  describe('clear', () => {
    it('clears the error', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      appError.setError('Error to clear');
      expect(appError.current).not.toBe(null);

      appError.clear();
      expect(appError.current).toBe(null);
    });

    it('does nothing when already null', async () => {
      const { appError } = await import('$stores/errorStore.svelte');
      appError.clear();
      expect(appError.current).toBe(null);
    });
  });
});
