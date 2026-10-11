import { createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
import {
    getSagaStatusApiV1SagasSagaIdGetOptions,
    listSagasApiV1SagasGetOptions,
    type SagaStatusResponse,
} from '#lib/api/index.ts';
import { type SagaStateFilter } from '#lib/admin/sagas/index.ts';

class SagasStore {
    #stateFilter = $state<SagaStateFilter>('');
    #executionIdFilter = $state('');
    #searchQuery = $state('');

    refreshEnabled = $state(true);
    refreshRate = $state(5);

    currentPage = $state(1);
    pageSize = $state(10);

    selectedSaga = $state<SagaStatusResponse | null>(null);

    #queryClient = useQueryClient();

    // --8<-- [start:list]
    list = createQuery(() => ({
        ...listSagasApiV1SagasGetOptions({
            query: {
                state: this.stateFilter || undefined,
                execution_id: this.executionIdFilter || undefined,
                search: this.searchQuery || undefined,
                limit: this.pageSize,
                skip: (this.currentPage - 1) * this.pageSize,
            },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: this.refreshEnabled ? this.refreshRate * 1000 : false,
    }));
    // --8<-- [end:list]

    sagas = $derived(this.list.data?.sagas ?? []);
    totalItems = $derived(this.list.data?.total ?? 0);
    totalPages = $derived(Math.ceil(this.totalItems / this.pageSize));

    // Each filter setter goes back to the first page, since the old page may not exist under the new filter
    get stateFilter(): SagaStateFilter {
        return this.#stateFilter;
    }
    set stateFilter(value: SagaStateFilter) {
        this.#stateFilter = value;
        this.currentPage = 1;
    }

    get executionIdFilter(): string {
        return this.#executionIdFilter;
    }
    set executionIdFilter(value: string) {
        this.#executionIdFilter = value;
        this.currentPage = 1;
    }

    get searchQuery(): string {
        return this.#searchQuery;
    }
    set searchQuery(value: string) {
        this.#searchQuery = value;
        this.currentPage = 1;
    }

    async openDetails(sagaId: string): Promise<void> {
        // A failed load already showed the interceptor's toast, so the modal just stays closed
        this.selectedSaga = await this.#queryClient
            .query(getSagaStatusApiV1SagasSagaIdGetOptions({ path: { saga_id: sagaId } }))
            .catch(() => null);
    }

    clearFilters(): void {
        this.stateFilter = '';
        this.executionIdFilter = '';
        this.searchQuery = '';
    }
}

export function createSagasStore(): SagasStore {
    return new SagasStore();
}
