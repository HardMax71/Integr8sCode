import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { toasts, addToast, removeToast, TOAST_DURATION } from '$stores/toastStore';

describe('toastStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Reset store state
    toasts.set([]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('addToast', () => {
    it('adds a toast with generated id', () => {
      addToast('Test message', 'success');
      const current = get(toasts);

      expect(current).toHaveLength(1);
      expect(current[0].message).toBe('Test message');
      expect(current[0].type).toBe('success');
      expect(current[0].id).toBeDefined();
    });

    it('defaults to info type when not specified', () => {
      addToast('Info message');
      const current = get(toasts);

      expect(current[0].type).toBe('info');
    });

    it('handles object messages with message property', () => {
      addToast({ message: 'Object message' }, 'warning');
      const current = get(toasts);

      expect(current[0].message).toBe('Object message');
    });

    it('handles object messages with detail property', () => {
      addToast({ detail: 'Detail message' }, 'error');
      const current = get(toasts);

      expect(current[0].message).toBe('Detail message');
    });

    it('prefers message over detail property', () => {
      addToast({ message: 'Message', detail: 'Detail' }, 'info');
      const current = get(toasts);

      expect(current[0].message).toBe('Message');
    });

    it('converts non-string values to string', () => {
      addToast(42, 'info');
      const current = get(toasts);

      expect(current[0].message).toBe('42');
    });

    it('handles null values', () => {
      addToast(null, 'info');
      const current = get(toasts);

      expect(current[0].message).toBe('null');
    });

    it('can add multiple toasts', () => {
      addToast('First', 'info');
      addToast('Second', 'success');
      addToast('Third', 'error');
      const current = get(toasts);

      expect(current).toHaveLength(3);
      expect(current[0].message).toBe('First');
      expect(current[1].message).toBe('Second');
      expect(current[2].message).toBe('Third');
    });

    it('generates unique ids for each toast', () => {
      addToast('First', 'info');
      addToast('Second', 'info');
      const current = get(toasts);

      expect(current[0].id).not.toBe(current[1].id);
    });
  });

  describe('removeToast', () => {
    it('removes a toast by id', () => {
      addToast('Test', 'info');
      const [toast] = get(toasts);

      removeToast(toast.id);

      expect(get(toasts)).toHaveLength(0);
    });

    it('removes only the specified toast', () => {
      addToast('First', 'info');
      addToast('Second', 'success');
      const [first] = get(toasts);

      removeToast(first.id);
      const remaining = get(toasts);

      expect(remaining).toHaveLength(1);
      expect(remaining[0].message).toBe('Second');
    });

    it('does nothing when id not found', () => {
      addToast('Test', 'info');

      removeToast('nonexistent-id');

      expect(get(toasts)).toHaveLength(1);
    });
  });

  describe('auto-removal', () => {
    it('auto-removes toast after TOAST_DURATION', () => {
      addToast('Temporary', 'warning');

      expect(get(toasts)).toHaveLength(1);

      vi.advanceTimersByTime(TOAST_DURATION + 100);

      expect(get(toasts)).toHaveLength(0);
    });

    it('does not remove toast before TOAST_DURATION', () => {
      addToast('Temporary', 'warning');

      vi.advanceTimersByTime(TOAST_DURATION - 100);

      expect(get(toasts)).toHaveLength(1);
    });

    it('removes multiple toasts at their respective times', () => {
      addToast('First', 'info');

      vi.advanceTimersByTime(1000);
      addToast('Second', 'success');

      // First toast should be removed after its duration (4000ms remaining)
      vi.advanceTimersByTime(TOAST_DURATION - 1000);
      expect(get(toasts)).toHaveLength(1);
      expect(get(toasts)[0].message).toBe('Second');

      // Second toast should be removed after its full duration (1000ms remaining)
      vi.advanceTimersByTime(1000);
      expect(get(toasts)).toHaveLength(0);
    });
  });

  describe('TOAST_DURATION constant', () => {
    it('is exported and equals 5000ms', () => {
      expect(TOAST_DURATION).toBe(5000);
    });
  });
});
