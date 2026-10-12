<script lang="ts">
    import { createQuery, keepPreviousData } from '@tanstack/svelte-query';
    import { listSagasApiV1SagasGetOptions } from '#lib/api/index.ts';
    import { AutoRefreshControl } from '#components/admin/index.ts';
    import { SagaStatsCards, SagaFilters, SagasTable, SagaDetailsModal } from '#components/admin/sagas/index.ts';
    import type { SagaListFilters } from '#components/admin/sagas/SagaFilters.svelte';

    const noFilters = (): SagaListFilters => ({ search: null, state: null, execution_id: null });
    let filters = $state(noFilters());
    let refreshEnabled = $state(true);
    let refreshRate = $state(5);
    let selectedSagaId = $state<string | null>(null);

    // A new filter goes back to the first page, since the old one may not exist under it
    let pageSize = $state(10);
    let pageIndex = $derived.by(() => {
        void { ...filters };
        return 0;
    });

    // --8<-- [start:list]
    const list = createQuery(() => ({
        ...listSagasApiV1SagasGetOptions({
            query: { ...filters, search: filters.search || null, limit: pageSize, skip: pageIndex * pageSize },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: refreshEnabled ? refreshRate * 1000 : false,
    }));
    // --8<-- [end:list]
    const sagas = $derived(list.data?.sagas ?? []);

    function showExecution(executionId: string): void {
        selectedSagaId = null;
        filters.execution_id = executionId;
    }
</script>

<div class="px-6 pb-6">
    <div class="mb-6">
        <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">Saga Management</h1>
        <p class="text-fg-muted dark:text-dark-fg-muted">Monitor and debug distributed transactions</p>
    </div>

    <SagaStatsCards {sagas} />

    <div class="mb-6">
        <AutoRefreshControl
            bind:enabled={refreshEnabled}
            bind:rate={refreshRate}
            loading={list.isFetching}
            onRefresh={() => list.refetch()}
        />
    </div>

    <SagaFilters bind:filters onClear={() => (filters = noFilters())} />

    <SagasTable
        {sagas}
        rowCount={list.data?.total ?? 0}
        bind:pagination={
            () => ({ pageIndex, pageSize }),
            (next) => {
                pageSize = next.pageSize;
                pageIndex = next.pageIndex;
            }
        }
        loading={list.isPending}
        onViewDetails={(id) => (selectedSagaId = id)}
        onViewExecution={showExecution}
    />
</div>

{#if selectedSagaId}
    <SagaDetailsModal sagaId={selectedSagaId} onClose={() => (selectedSagaId = null)} onViewExecution={showExecution} />
{/if}
