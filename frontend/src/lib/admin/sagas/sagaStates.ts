/**
 * Saga state configurations
 */
import { Plus, Loader, TriangleAlert, CircleCheckBig, CircleX, Clock } from '@lucide/svelte';
import type { SagaState } from '#lib/api/index.ts';

export interface SagaStateConfig {
    color: string;
    bgColor: string;
    icon: typeof CircleCheckBig;
}

export const SAGA_STATES: Record<SagaState, SagaStateConfig> = {
    created: {
        color: 'badge-neutral',
        bgColor: 'bg-muted',
        icon: Plus,
    },
    running: {
        color: 'badge-info',
        bgColor: 'bg-info-soft',
        icon: Loader,
    },
    compensating: {
        color: 'badge-warning',
        bgColor: 'bg-warning-soft',
        icon: TriangleAlert,
    },
    completed: {
        color: 'badge-success',
        bgColor: 'bg-success-soft',
        icon: CircleCheckBig,
    },
    failed: {
        color: 'badge-danger',
        bgColor: 'bg-danger-soft',
        icon: CircleX,
    },
    timeout: {
        color: 'badge-warning',
        bgColor: 'bg-orange-soft',
        icon: Clock,
    },
    cancelled: {
        color: 'badge-neutral',
        bgColor: 'bg-muted',
        icon: CircleX,
    },
};

export function getSagaStateInfo(state: SagaState): SagaStateConfig {
    return SAGA_STATES[state];
}

// Filter type for saga state filters - empty string means "all"
