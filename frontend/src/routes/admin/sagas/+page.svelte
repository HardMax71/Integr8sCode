<script lang="ts">
    import { AutoRefreshControl } from '#components/admin/index.ts';
    import { SagaStatsCards, SagaFilters, SagasTable, SagaDetailsModal } from '#components/admin/sagas/index.ts';
    import { createSagasStore } from '#lib/admin/stores/sagasStore.svelte.ts';

    const store = createSagasStore();

    function showExecution(executionId: string): void {
        store.selectedSaga = null;
        store.executionIdFilter = executionId;
    }
</script>

<div class="px-6 pb-6">
    <div class="mb-6">
        <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">Saga Management</h1>
        <p class="text-fg-muted dark:text-dark-fg-muted">Monitor and debug distributed transactions</p>
    </div>

    <SagaStatsCards sagas={store.sagas} />

    <div class="mb-6">
        <AutoRefreshControl
            bind:enabled={store.refreshEnabled}
            bind:rate={store.refreshRate}
            loading={store.list.isFetching}
            onRefresh={() => store.list.refetch()}
        />
    </div>

    <SagaFilters
        bind:searchQuery={store.searchQuery}
        bind:stateFilter={store.stateFilter}
        bind:executionIdFilter={store.executionIdFilter}
        onClear={() => store.clearFilters()}
    />

    <SagasTable
        sagas={store.sagas}
        rowCount={store.totalItems}
        bind:pagination={store.pagination}
        loading={store.list.isPending}
        onViewDetails={(id) => store.openDetails(id)}
        onViewExecution={showExecution}
    />
</div>

{#if store.selectedSaga}
    <SagaDetailsModal
        saga={store.selectedSaga}
        open={store.selectedSaga !== null}
        onClose={() => (store.selectedSaga = null)}
        onViewExecution={showExecution}
    />
{/if}
