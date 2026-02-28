<script lang="ts">
    import { onMount, untrack } from 'svelte';
    import {
        getSagaStatusApiV1SagasSagaIdGet,
        type SagaStatusResponse,
    } from '$lib/api';
    import { unwrapOr } from '$lib/api-interceptors';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Pagination from '$components/Pagination.svelte';
    import { AutoRefreshControl } from '$components/admin';
    import {
        SagaStatsCards,
        SagaFilters,
        SagasTable,
        SagaDetailsModal
    } from '$components/admin/sagas';
    import { createSagasStore } from '$lib/admin/stores/sagasStore.svelte';

    const store = createSagasStore();

    // Modal-only state
    let selectedSaga = $state<SagaStatusResponse | null>(null);
    let showDetailModal = $state(false);

    let totalPages = $derived(Math.ceil(store.totalItems / store.pagination.pageSize));

    async function loadSagaDetails(sagaId: string): Promise<void> {
        const data = unwrapOr(await getSagaStatusApiV1SagasSagaIdGet({
            path: { saga_id: sagaId }
        }), null);
        if (!data) return;
        selectedSaga = data;
        showDetailModal = true;
    }

    function handleViewExecution(executionId: string): void {
        showDetailModal = false;
        store.loadExecutionSagas(executionId);
    }

    function handlePageChange(page: number): void {
        store.pagination.handlePageChange(page, () => store.loadSagas());
    }

    function handlePageSizeChange(size: number): void {
        store.pagination.handlePageSizeChange(size, () => store.loadSagas());
    }

    let prevStateFilter = $state(store.stateFilter);
    $effect(() => {
        if (store.stateFilter !== prevStateFilter) {
            prevStateFilter = store.stateFilter;
            untrack(() => {
                store.pagination.currentPage = 1;
                store.loadSagas();
            });
        }
    });

    onMount(() => {
        store.loadSagas();
    });
</script>

<AdminLayout path="/admin/sagas">
    <div class="px-6 pb-6">
        <div class="mb-6">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">
                Saga Management
            </h1>
            <p class="text-fg-muted dark:text-dark-fg-muted">
                Monitor and debug distributed transactions
            </p>
        </div>

        <SagaStatsCards sagas={store.sagas} />

        <div class="mb-6">
            <AutoRefreshControl
                bind:enabled={store.refreshEnabled}
                bind:rate={store.refreshRate}
                loading={store.loading}
                onRefresh={() => store.loadSagas()}
            />
        </div>

        <SagaFilters
            bind:searchQuery={store.searchQuery}
            bind:stateFilter={store.stateFilter}
            bind:executionIdFilter={store.executionIdFilter}
            onSearch={() => store.loadSagas()}
            onClear={() => store.clearFilters()}
        />

        <SagasTable
            sagas={store.sagas}
            loading={store.loading}
            onViewDetails={loadSagaDetails}
            onViewExecution={(id) => store.loadExecutionSagas(id)}
        />

        {#if store.totalItems > 0}
            <div class="p-4 border-t divider">
                {#if store.hasClientFilters && store.sagas.length < store.serverReturnedCount}
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-2">
                        Showing {store.sagas.length} of {store.serverReturnedCount} on this page (filtered locally)
                    </p>
                {/if}
                <Pagination
                    currentPage={store.pagination.currentPage}
                    {totalPages}
                    totalItems={store.totalItems}
                    pageSize={store.pagination.pageSize}
                    onPageChange={handlePageChange}
                    onPageSizeChange={handlePageSizeChange}
                    itemName="sagas"
                />
            </div>
        {/if}
    </div>
</AdminLayout>

{#if showDetailModal && selectedSaga}
    <SagaDetailsModal
        saga={selectedSaga}
        open={showDetailModal}
        onClose={() => showDetailModal = false}
        onViewExecution={handleViewExecution}
    />
{/if}
