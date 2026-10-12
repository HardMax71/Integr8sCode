import type { ExecutionStatus } from '#lib/api/index.ts';

export const EXECUTION_STATUS_BADGE: Record<ExecutionStatus, string> = {
    queued: 'badge-neutral',
    scheduled: 'badge-neutral',
    running: 'badge-info',
    completed: 'badge-success',
    failed: 'badge-danger',
    timeout: 'badge-warning',
    cancelled: 'badge-neutral',
    error: 'badge-danger',
};
