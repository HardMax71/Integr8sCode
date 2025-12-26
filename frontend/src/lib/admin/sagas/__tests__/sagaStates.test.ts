import { describe, it, expect } from 'vitest';
import {
  SAGA_STATES,
  getSagaStateInfo,
  EXECUTION_SAGA_STEPS,
  getSagaProgressPercentage
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

    it('returns default for unknown state', () => {
      const unknown = getSagaStateInfo('unknown_state');
      expect(unknown.label).toBe('unknown_state');
      expect(unknown.color).toBe('badge-neutral');
    });
  });

  describe('EXECUTION_SAGA_STEPS', () => {
    it('has 5 steps', () => {
      expect(EXECUTION_SAGA_STEPS).toHaveLength(5);
    });

    it('each step has required properties', () => {
      EXECUTION_SAGA_STEPS.forEach(step => {
        expect(step).toHaveProperty('name');
        expect(step).toHaveProperty('label');
        expect(step).toHaveProperty('compensation');
      });
    });

    it('has correct step names', () => {
      const names = EXECUTION_SAGA_STEPS.map(s => s.name);
      expect(names).toContain('validate_execution');
      expect(names).toContain('allocate_resources');
      expect(names).toContain('create_pod');
    });

    it('has compensations for some steps', () => {
      const allocate = EXECUTION_SAGA_STEPS.find(s => s.name === 'allocate_resources');
      expect(allocate?.compensation).toBe('release_resources');

      const validate = EXECUTION_SAGA_STEPS.find(s => s.name === 'validate_execution');
      expect(validate?.compensation).toBeNull();
    });
  });

  describe('getSagaProgressPercentage', () => {
    it('returns 0 for empty steps', () => {
      expect(getSagaProgressPercentage([], 'execution_saga')).toBe(0);
    });

    it('returns 0 for null/undefined steps', () => {
      expect(getSagaProgressPercentage(null as unknown as string[], 'execution_saga')).toBe(0);
      expect(getSagaProgressPercentage(undefined as unknown as string[], 'execution_saga')).toBe(0);
    });

    it('calculates correct percentage for execution_saga', () => {
      expect(getSagaProgressPercentage(['step1'], 'execution_saga')).toBe(20);
      expect(getSagaProgressPercentage(['step1', 'step2'], 'execution_saga')).toBe(40);
      expect(getSagaProgressPercentage(['s1', 's2', 's3', 's4', 's5'], 'execution_saga')).toBe(100);
    });

    it('calculates correct percentage for other sagas (3 steps)', () => {
      expect(getSagaProgressPercentage(['step1'], 'other_saga')).toBeCloseTo(33.33, 0);
      expect(getSagaProgressPercentage(['step1', 'step2', 'step3'], 'other_saga')).toBe(100);
    });

    it('caps at 100%', () => {
      expect(getSagaProgressPercentage(['s1', 's2', 's3', 's4', 's5', 's6'], 'execution_saga')).toBe(100);
    });
  });
});
