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
        bgColor: 'bg-neutral-50 dark:bg-neutral-900/20',
        icon: Plus,
    },
    running: {
        color: 'badge-info',
        bgColor: 'bg-blue-50 dark:bg-blue-900/20',
        icon: Loader,
    },
    compensating: {
        color: 'badge-warning',
        bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
        icon: TriangleAlert,
    },
    completed: {
        color: 'badge-success',
        bgColor: 'bg-green-50 dark:bg-green-900/20',
        icon: CircleCheckBig,
    },
    failed: {
        color: 'badge-danger',
        bgColor: 'bg-red-50 dark:bg-red-900/20',
        icon: CircleX,
    },
    timeout: {
        color: 'badge-warning',
        bgColor: 'bg-orange-50 dark:bg-orange-900/20',
        icon: Clock,
    },
    cancelled: {
        color: 'badge-neutral',
        bgColor: 'bg-neutral-50 dark:bg-neutral-900/20',
        icon: CircleX,
    },
};

export function getSagaStateInfo(state: SagaState): SagaStateConfig {
    return SAGA_STATES[state];
}

// Filter type for saga state filters - empty string means "all"
