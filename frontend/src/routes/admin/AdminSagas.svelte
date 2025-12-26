<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import {
        listSagasApiV1SagasGet,
        getSagaStatusApiV1SagasSagaIdGet,
        getExecutionSagasApiV1SagasExecutionExecutionIdGet,
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
    import { type SagaStateFilter } from '$lib/admin/sagas';

    // State
    let loading = $state(true);
    let sagas = $state<SagaStatusResponse[]>([]);
    let selectedSaga = $state<SagaStatusResponse | null>(null);
    let showDetailModal = $state(false);

    // Auto-refresh
    let refreshInterval: ReturnType<typeof setInterval> | null = null;
    let autoRefresh = $state(true);
    let refreshRate = $state(5);

    // Filters
    let stateFilter = $state<SagaStateFilter>('');
    let executionIdFilter = $state('');
    let searchQuery = $state('');

    // Pagination
    let currentPage = $state(1);
    let pageSize = $state(10);
    let totalItems = $state(0);
    let serverReturnedCount = $state(0); // Items returned by server before client-side filtering
    // When client-side filters are active, pagination reflects server totals (current page filtering only)
    let hasClientFilters = $derived(Boolean(executionIdFilter || searchQuery));
    let totalPages = $derived(Math.ceil(totalItems / pageSize));

    async function loadSagas(): Promise<void> {
        loading = true;
        const data = unwrapOr(await listSagasApiV1SagasGet({
            query: {
                state: stateFilter || undefined,
                limit: pageSize,
                offset: (currentPage - 1) * pageSize
            }
        }), null);
        loading = false;

        let result = data?.sagas || [];
        totalItems = data?.total || 0;
        serverReturnedCount = result.length;

        // Client-side filtering for execution ID and search (filters within current page only)
        if (executionIdFilter) {
            result = result.filter(s => s.execution_id.includes(executionIdFilter));
        }
        if (searchQuery) {
            const q = searchQuery.toLowerCase();
            result = result.filter(s =>
                s.saga_id.toLowerCase().includes(q) ||
                s.saga_name.toLowerCase().includes(q) ||
                s.execution_id.toLowerCase().includes(q) ||
                s.error_message?.toLowerCase().includes(q)
            );
        }
        sagas = result;
    }

    async function loadSagaDetails(sagaId: string): Promise<void> {
        const data = unwrapOr(await getSagaStatusApiV1SagasSagaIdGet({
            path: { saga_id: sagaId }
        }), null);
        if (!data) return;
        selectedSaga = data;
        showDetailModal = true;
    }

    async function loadExecutionSagas(executionId: string): Promise<void> {
        loading = true;
        const data = unwrapOr(await getExecutionSagasApiV1SagasExecutionExecutionIdGet({
            path: { execution_id: executionId }
        }), null);
        loading = false;
        sagas = data?.sagas || [];
        totalItems = data?.total || 0;
        executionIdFilter = executionId;
    }

    function setupAutoRefresh(): void {
        if (refreshInterval) clearInterval(refreshInterval);
        if (autoRefresh) {
            refreshInterval = setInterval(loadSagas, refreshRate * 1000);
        }
    }

    function clearFilters(): void {
        stateFilter = '';
        executionIdFilter = '';
        searchQuery = '';
        currentPage = 1;
        loadSagas();
    }

    function handlePageChange(page: number): void {
        currentPage = page;
        loadSagas();
    }

    function handlePageSizeChange(size: number): void {
        pageSize = size;
        currentPage = 1;
        loadSagas();
    }

    function handleViewExecution(executionId: string): void {
        showDetailModal = false;
        loadExecutionSagas(executionId);
    }

    onMount(() => {
        loadSagas();
        setupAutoRefresh();
    });

    onDestroy(() => {
        if (refreshInterval) clearInterval(refreshInterval);
    });

    // Re-setup auto-refresh when settings change
    $effect(() => {
        if (autoRefresh || refreshRate) {
            setupAutoRefresh();
        }
    });

    // Reset page when filter changes
    let prevStateFilter = '';
    $effect(() => {
        if (stateFilter !== prevStateFilter) {
            prevStateFilter = stateFilter;
            currentPage = 1;
            loadSagas();
        }
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

        <SagaStatsCards {sagas} />

        <div class="mb-6">
            <AutoRefreshControl
                bind:enabled={autoRefresh}
                bind:rate={refreshRate}
                {loading}
                onRefresh={loadSagas}
            />
        </div>

        <SagaFilters
            bind:searchQuery
            bind:stateFilter
            bind:executionIdFilter
            onSearch={loadSagas}
            onClear={clearFilters}
        />

        <SagasTable
            {sagas}
            {loading}
            onViewDetails={loadSagaDetails}
            onViewExecution={loadExecutionSagas}
        />

        {#if totalItems > 0}
            <div class="p-4 border-t divider">
                {#if hasClientFilters && sagas.length < serverReturnedCount}
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-2">
                        Showing {sagas.length} of {serverReturnedCount} on this page (filtered locally)
                    </p>
                {/if}
                <Pagination
                    {currentPage}
                    {totalPages}
                    {totalItems}
                    {pageSize}
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
