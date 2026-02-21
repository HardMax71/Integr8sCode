import { describe, it, expect } from 'vitest';
import {
  SAGA_STATES,
  getSagaStateInfo,
} from '$lib/admin/sagas/sagaStates';

describe('sagaStates', () => {
  describe('SAGA_STATES', () => {
    it('has all expected states', () => {
      expect(SAGA_STATES.created).toBeDefined();
      expect(SAGA_STATES.running).toBeDefined();
      expect(SAGA_STATES.compensating).toBeDefined();
      expect(SAGA_STATES.completed).toBeDefined();
      expect(SAGA_STATES.failed).toBeDefined();
      expect(SAGA_STATES.timeout).toBeDefined();
    });

    it('each state has required properties', () => {
      Object.values(SAGA_STATES).forEach(state => {
        expect(state).toHaveProperty('label');
        expect(state).toHaveProperty('color');
        expect(state).toHaveProperty('bgColor');
        expect(state).toHaveProperty('icon');
      });
    });

    it('has correct labels', () => {
      expect(SAGA_STATES.created.label).toBe('Created');
      expect(SAGA_STATES.running.label).toBe('Running');
      expect(SAGA_STATES.completed.label).toBe('Completed');
      expect(SAGA_STATES.failed.label).toBe('Failed');
    });
  });

  describe('getSagaStateInfo', () => {
    it('returns correct info for known states', () => {
      const running = getSagaStateInfo('running');
      expect(running.label).toBe('Running');
      expect(running.color).toBe('badge-info');
    });

    it('returns info for all valid states', () => {
      const states = ['created', 'running', 'compensating', 'completed', 'failed', 'timeout', 'cancelled'] as const;
      for (const state of states) {
        const info = getSagaStateInfo(state);
        expect(info.label).toBeTruthy();
        expect(info.color).toBeTruthy();
      }
    });
  });
});
