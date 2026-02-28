import {
    listSagasApiV1SagasGet,
    type SagaStatusResponse,
} from '$lib/api';
import { unwrapOr } from '$lib/api-interceptors';
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

    refreshEnabled = $state(true);
    refreshRate = $state(5);

    pagination = createPaginationState({ initialPageSize: 10 });

    constructor() {
        $effect(() => {
            if (!this.refreshEnabled) return;
            const id = setInterval(() => this.loadSagas(), this.refreshRate * 1000);
            return () => { clearInterval(id); };
        });
    }

    async loadSagas(): Promise<void> {
        this.loading = true;
        const data = unwrapOr(await listSagasApiV1SagasGet({
            query: {
                state: this.stateFilter || undefined,
                execution_id: this.executionIdFilter || undefined,
                limit: this.pagination.pageSize,
                skip: this.pagination.skip,
            }
        }), null);
        this.loading = false;

        let result = data?.sagas || [];
        this.totalItems = data?.total || 0;
        this.serverReturnedCount = result.length;

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
        this.executionIdFilter = executionId;
        this.pagination.currentPage = 1;
        await this.loadSagas();
    }

    clearFilters(): void {
        this.stateFilter = '';
        this.executionIdFilter = '';
        this.searchQuery = '';
        this.pagination.currentPage = 1;
        void this.loadSagas();
    }
}

export function createSagasStore(): SagasStore {
    return new SagasStore();
}
