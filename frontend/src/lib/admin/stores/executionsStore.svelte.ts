import {
    listExecutionsApiV1AdminExecutionsGet,
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut,
    getQueueStatusApiV1AdminExecutionsQueueGet,
    type AdminExecutionResponse,
    type QueueStatusResponse,
    type QueuePriority,
    type ExecutionStatus,
} from '$lib/api';
import { unwrap, unwrapOr } from '$lib/api-interceptors';
import { toast } from 'svelte-sonner';
import { createAutoRefresh } from '../autoRefresh.svelte';
import { createPaginationState } from '../pagination.svelte';

class ExecutionsStore {
    executions = $state<AdminExecutionResponse[]>([]);
    total = $state(0);
    loading = $state(false);
    queueStatus = $state<QueueStatusResponse | null>(null);

    statusFilter = $state<'all' | ExecutionStatus>('all');
    priorityFilter = $state<'all' | QueuePriority>('all');
    userSearch = $state('');

    pagination = createPaginationState({ initialPageSize: 20 });
    autoRefresh = createAutoRefresh({
        onRefresh: () => this.loadData(),
        initialRate: 5,
        initialEnabled: true,
    });

    async loadData(): Promise<void> {
        await Promise.all([this.loadExecutions(), this.loadQueueStatus()]);
    }

    async loadExecutions(): Promise<void> {
        this.loading = true;
        const data = unwrapOr(await listExecutionsApiV1AdminExecutionsGet({
            query: {
                limit: this.pagination.pageSize,
                skip: this.pagination.skip,
                status: this.statusFilter !== 'all' ? this.statusFilter : undefined,
                priority: this.priorityFilter !== 'all' ? this.priorityFilter : undefined,
                user_id: this.userSearch || undefined,
            },
        }), null);
        this.executions = data?.executions || [];
        this.total = data?.total || 0;
        this.loading = false;
    }

    async loadQueueStatus(): Promise<void> {
        const data = unwrapOr(await getQueueStatusApiV1AdminExecutionsQueueGet({}), null);
        if (data) {
            this.queueStatus = data;
        }
    }

    async updatePriority(executionId: string, newPriority: QueuePriority): Promise<void> {
        unwrap(await updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut({
            path: { execution_id: executionId },
            body: { priority: newPriority },
        }));
        toast.success(`Priority updated to ${newPriority}`);
        await this.loadData();
    }

    resetFilters(): void {
        this.statusFilter = 'all';
        this.priorityFilter = 'all';
        this.userSearch = '';
    }

    cleanup(): void {
        this.autoRefresh.cleanup();
    }
}

export function createExecutionsStore(): ExecutionsStore {
    return new ExecutionsStore();
}
