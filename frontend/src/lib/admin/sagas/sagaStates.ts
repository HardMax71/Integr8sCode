/**
 * Saga state configurations
 */
import { Plus, Loader, AlertTriangle, CheckCircle, XCircle, Clock } from '@lucide/svelte';
import type { SagaState } from '$lib/api';

export interface SagaStateConfig {
    label: string;
    color: string;
    bgColor: string;
    icon: typeof CheckCircle;
}

export const SAGA_STATES: Record<SagaState, SagaStateConfig> = {
    created: {
        label: 'Created',
        color: 'badge-neutral',
        bgColor: 'bg-neutral-50 dark:bg-neutral-900/20',
        icon: Plus
    },
    running: {
        label: 'Running',
        color: 'badge-info',
        bgColor: 'bg-blue-50 dark:bg-blue-900/20',
        icon: Loader
    },
    compensating: {
        label: 'Compensating',
        color: 'badge-warning',
        bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
        icon: AlertTriangle
    },
    completed: {
        label: 'Completed',
        color: 'badge-success',
        bgColor: 'bg-green-50 dark:bg-green-900/20',
        icon: CheckCircle
    },
    failed: {
        label: 'Failed',
        color: 'badge-danger',
        bgColor: 'bg-red-50 dark:bg-red-900/20',
        icon: XCircle
    },
    timeout: {
        label: 'Timeout',
        color: 'badge-warning',
        bgColor: 'bg-orange-50 dark:bg-orange-900/20',
        icon: Clock
    },
    cancelled: {
        label: 'Cancelled',
        color: 'badge-neutral',
        bgColor: 'bg-neutral-50 dark:bg-neutral-900/20',
        icon: XCircle
    }
};

const DEFAULT_STATE: SagaStateConfig = {
    label: 'Unknown',
    color: 'badge-neutral',
    bgColor: 'bg-neutral-50',
    icon: Plus
};

export function getSagaStateInfo(state: SagaState | string): SagaStateConfig {
    return SAGA_STATES[state] || { ...DEFAULT_STATE, label: state };
}

// Execution saga step definitions
export interface SagaStep {
    name: string;
    label: string;
    compensation: string | null;
}

export const EXECUTION_SAGA_STEPS: SagaStep[] = [
    { name: 'validate_execution', label: 'Validate', compensation: null },
    { name: 'allocate_resources', label: 'Allocate Resources', compensation: 'release_resources' },
    { name: 'queue_execution', label: 'Queue Execution', compensation: 'remove_from_queue' },
    { name: 'create_pod', label: 'Create Pod', compensation: 'delete_pod' },
    { name: 'monitor_execution', label: 'Monitor', compensation: null }
];

export function getSagaProgressPercentage(completedSteps: string[], sagaName: string): number {
    if (!completedSteps?.length) return 0;
    const totalSteps = sagaName === 'execution_saga' ? 5 : 3;
    return Math.min(100, (completedSteps.length / totalSteps) * 100);
}
