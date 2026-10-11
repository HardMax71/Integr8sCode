import { createMutation, createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
import {
    getQueueStatusApiV1AdminExecutionsQueueGetOptions,
    getQueueStatusApiV1AdminExecutionsQueueGetQueryKey,
    listExecutionsApiV1AdminExecutionsGetOptions,
    listExecutionsApiV1AdminExecutionsGetQueryKey,
    updatePriorityApiV1AdminExecutionsExecutionIdPriorityPutMutation,
    type ExecutionStatus,
    type QueuePriority,
} from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';

const POLL_INTERVAL_MS = 5_000;

class ExecutionsStore {
    #statusFilter = $state<'all' | ExecutionStatus>('all');
    #priorityFilter = $state<'all' | QueuePriority>('all');
    #userSearch = $state('');

    currentPage = $state(1);
    pageSize = $state(20);

    #queryClient = useQueryClient();

    list = createQuery(() => ({
        ...listExecutionsApiV1AdminExecutionsGetOptions({
            query: {
                limit: this.pageSize,
                skip: (this.currentPage - 1) * this.pageSize,
                status: this.statusFilter !== 'all' ? this.statusFilter : undefined,
                priority: this.priorityFilter !== 'all' ? this.priorityFilter : undefined,
                user_id: this.userSearch || undefined,
            },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: POLL_INTERVAL_MS,
    }));

    queueStatus = createQuery(() => ({
        ...getQueueStatusApiV1AdminExecutionsQueueGetOptions(),
        refetchInterval: POLL_INTERVAL_MS,
    }));

    updatePriority = createMutation(() => ({
        ...updatePriorityApiV1AdminExecutionsExecutionIdPriorityPutMutation(),
        onSuccess: (_data, { body }) => {
            toast.success(`Priority updated to ${body.priority}`);
            return this.refresh();
        },
    }));

    executions = $derived(this.list.data?.executions ?? []);
    total = $derived(this.list.data?.total ?? 0);
    totalPages = $derived(Math.ceil(this.total / this.pageSize));

    // Each filter setter goes back to the first page, since the old page may not exist under the new filter
    get statusFilter(): 'all' | ExecutionStatus {
        return this.#statusFilter;
    }
    set statusFilter(value: 'all' | ExecutionStatus) {
        this.#statusFilter = value;
        this.currentPage = 1;
    }

    get priorityFilter(): 'all' | QueuePriority {
        return this.#priorityFilter;
    }
    set priorityFilter(value: 'all' | QueuePriority) {
        this.#priorityFilter = value;
        this.currentPage = 1;
    }

    get userSearch(): string {
        return this.#userSearch;
    }
    set userSearch(value: string) {
        this.#userSearch = value;
        this.currentPage = 1;
    }

    async refresh(): Promise<void> {
        await Promise.all([
            this.#queryClient.invalidateQueries({ queryKey: listExecutionsApiV1AdminExecutionsGetQueryKey() }),
            this.#queryClient.invalidateQueries({ queryKey: getQueueStatusApiV1AdminExecutionsQueueGetQueryKey() }),
        ]);
    }

    resetFilters(): void {
        this.statusFilter = 'all';
        this.priorityFilter = 'all';
        this.userSearch = '';
    }
}

export function createExecutionsStore(): ExecutionsStore {
    return new ExecutionsStore();
}
