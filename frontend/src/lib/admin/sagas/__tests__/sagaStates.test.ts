import { describe, it, expect } from 'vitest';
import { SagaState } from '#lib/api/index.ts';
import { SAGA_STATES, getSagaStateInfo } from '#lib/admin/sagas/sagaStates.ts';

describe('sagaStates', () => {
    describe('SAGA_STATES', () => {
        it('covers every state the API sends', () => {
            expect(Object.keys(SAGA_STATES).sort()).toEqual(Object.values(SagaState).sort());
        });

        it('each state has required properties', () => {
            Object.values(SAGA_STATES).forEach((state) => {
                expect(state).toHaveProperty('color');
                expect(state).toHaveProperty('bgColor');
                expect(state).toHaveProperty('icon');
            });
        });
    });

    describe('getSagaStateInfo', () => {
        it('returns correct info for known states', () => {
            const running = getSagaStateInfo('running');
            expect(running.color).toBe('badge-info');
        });

        it('returns info for all valid states', () => {
            for (const state of Object.values(SagaState)) {
                const info = getSagaStateInfo(state);
                expect(info.color).toBeTruthy();
            }
        });
    });
});
