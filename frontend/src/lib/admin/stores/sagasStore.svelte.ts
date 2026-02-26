import {
    listSagasApiV1SagasGet,
    getExecutionSagasApiV1SagasExecutionExecutionIdGet,
    type SagaStatusResponse,
} from '$lib/api';
import { unwrapOr } from '$lib/api-interceptors';
import { createAutoRefresh } from '../autoRefresh.svelte';
import { createPaginationState } from '../pagination.svelte';
import { type SagaStateFilter } from '$lib/admin/sagas';

class SagasStore {
    sagas = $state<SagaStatusResponse[]>([]);
    loading = $state(true);
    totalItems = $state(0);
    serverReturnedCount = $state(0);

    stateFilter = $state<SagaStateFilter>('');
    executionIdFilter = $state('');
    searchQuery = $state('');

    hasClientFilters = $derived(Boolean(this.executionIdFilter || this.searchQuery));

    pagination = createPaginationState({ initialPageSize: 10 });
    autoRefresh = createAutoRefresh({
        onRefresh: () => this.loadSagas(),
        initialRate: 5,
        initialEnabled: true,
    });

    async loadSagas(): Promise<void> {
        this.loading = true;
        const data = unwrapOr(await listSagasApiV1SagasGet({
            query: {
                state: this.stateFilter || undefined,
                limit: this.pagination.pageSize,
                skip: this.pagination.skip,
            }
        }), null);
        this.loading = false;

        let result = data?.sagas || [];
        this.totalItems = data?.total || 0;
        this.serverReturnedCount = result.length;

        if (this.executionIdFilter) {
            result = result.filter(s => s.execution_id.includes(this.executionIdFilter));
        }
        if (this.searchQuery) {
            const q = this.searchQuery.toLowerCase();
            result = result.filter(s =>
                s.saga_id.toLowerCase().includes(q) ||
                s.saga_name.toLowerCase().includes(q) ||
                s.execution_id.toLowerCase().includes(q) ||
                s.error_message?.toLowerCase().includes(q)
            );
        }
        this.sagas = result;
    }

    async loadExecutionSagas(executionId: string): Promise<void> {
        this.loading = true;
        const data = unwrapOr(await getExecutionSagasApiV1SagasExecutionExecutionIdGet({
            path: { execution_id: executionId }
        }), null);
        this.loading = false;
        this.sagas = data?.sagas || [];
        this.totalItems = data?.total || 0;
        this.executionIdFilter = executionId;
    }

    clearFilters(): void {
        this.stateFilter = '';
        this.executionIdFilter = '';
        this.searchQuery = '';
        this.pagination.currentPage = 1;
        void this.loadSagas();
    }

    cleanup(): void {
        this.autoRefresh.cleanup();
    }
}

export function createSagasStore(): SagasStore {
    return new SagasStore();
}
