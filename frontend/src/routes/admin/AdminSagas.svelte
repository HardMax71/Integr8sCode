<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import {
        listSagasApiV1SagasGet,
        getSagaStatusApiV1SagasSagaIdGet,
        getExecutionSagasApiV1SagasExecutionExecutionIdGet,
        type SagaStatusResponse,
        type SagaState,
    } from '../../lib/api';
    import { unwrap, unwrapOr } from '../../lib/api-interceptors';
    import { formatTimestamp, formatDurationBetween } from '../../lib/formatters';
    import AdminLayout from './AdminLayout.svelte';
    import Spinner from '../../components/Spinner.svelte';
    import Modal from '../../components/Modal.svelte';
    import Pagination from '../../components/Pagination.svelte';
    import { Plus, RefreshCw, AlertTriangle, CheckCircle, XCircle, Clock, Loader, X, Check, Undo2 } from '@lucide/svelte';

    let loading = $state(true);
    let sagas = $state<SagaStatusResponse[]>([]);
    let selectedSaga = $state<SagaStatusResponse | null>(null);
    let showDetailModal = $state(false);
    let refreshInterval: ReturnType<typeof setInterval> | null = null;
    let autoRefresh = $state(true);
    let refreshRate = $state(5);

    let stateFilter = $state('');
    let executionIdFilter = $state('');
    let searchQuery = $state('');

    let currentPage = $state(1);
    let pageSize = $state(10);
    let totalItems = $state(0);

    const sagaStates: Record<string, { label: string; color: string; bgColor: string; icon: typeof CheckCircle }> = {
        created: { label: 'Created', color: 'badge-neutral', bgColor: 'bg-neutral-50 dark:bg-neutral-900/20', icon: Plus },
        running: { label: 'Running', color: 'badge-info', bgColor: 'bg-blue-50 dark:bg-blue-900/20', icon: Loader },
        compensating: { label: 'Compensating', color: 'badge-warning', bgColor: 'bg-yellow-50 dark:bg-yellow-900/20', icon: AlertTriangle },
        completed: { label: 'Completed', color: 'badge-success', bgColor: 'bg-green-50 dark:bg-green-900/20', icon: CheckCircle },
        failed: { label: 'Failed', color: 'badge-danger', bgColor: 'bg-red-50 dark:bg-red-900/20', icon: XCircle },
        timeout: { label: 'Timeout', color: 'badge-warning', bgColor: 'bg-orange-50 dark:bg-orange-900/20', icon: Clock },
    };

    const executionSagaSteps = [
        { name: 'validate_execution', label: 'Validate', compensation: null },
        { name: 'allocate_resources', label: 'Allocate Resources', compensation: 'release_resources' },
        { name: 'queue_execution', label: 'Queue Execution', compensation: 'remove_from_queue' },
        { name: 'create_pod', label: 'Create Pod', compensation: 'delete_pod' },
        { name: 'monitor_execution', label: 'Monitor', compensation: null }
    ];

    async function loadSagas(): Promise<void> {
        loading = true;
        const data = unwrapOr(await listSagasApiV1SagasGet({
            query: { state: stateFilter || undefined, limit: pageSize, offset: (currentPage - 1) * pageSize }
        }), null);
        loading = false;
        sagas = data?.sagas || [];
        totalItems = data?.total || 0;

        if (executionIdFilter) sagas = sagas.filter(s => s.execution_id.includes(executionIdFilter));
        if (searchQuery) {
            const q = searchQuery.toLowerCase();
            sagas = sagas.filter(s =>
                s.saga_id.toLowerCase().includes(q) || s.saga_name.toLowerCase().includes(q) ||
                s.execution_id.toLowerCase().includes(q) || s.error_message?.toLowerCase().includes(q)
            );
        }
    }

    async function loadSagaDetails(sagaId: string): Promise<void> {
        const data = unwrapOr(await getSagaStatusApiV1SagasSagaIdGet({ path: { saga_id: sagaId } }), null);
        if (!data) return;
        selectedSaga = data;
        showDetailModal = true;
    }

    async function loadExecutionSagas(executionId: string): Promise<void> {
        loading = true;
        const data = unwrapOr(await getExecutionSagasApiV1SagasExecutionExecutionIdGet({ path: { execution_id: executionId } }), null);
        loading = false;
        sagas = data?.sagas || [];
        totalItems = data?.total || 0;
        executionIdFilter = executionId;
    }

    function getStateInfo(state: SagaState | string) {
        return sagaStates[state as SagaState] || { label: state, color: 'badge-neutral', bgColor: 'bg-neutral-50', icon: Plus };
    }

    function getProgressPercentage(saga: SagaStatusResponse): number {
        if (!saga.completed_steps?.length) return 0;
        const totalSteps = saga.saga_name === 'execution_saga' ? 5 : 3;
        return Math.min(100, (saga.completed_steps.length / totalSteps) * 100);
    }

    function setupAutoRefresh(): void {
        if (refreshInterval) clearInterval(refreshInterval);
        if (autoRefresh) refreshInterval = setInterval(loadSagas, refreshRate * 1000);
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

    onMount(() => { loadSagas(); setupAutoRefresh(); });
    onDestroy(() => { if (refreshInterval) clearInterval(refreshInterval); });

    $effect(() => { if (autoRefresh || refreshRate) setupAutoRefresh(); });

    let prevStateFilter = '';
    $effect(() => {
        if (stateFilter !== prevStateFilter) {
            prevStateFilter = stateFilter;
            currentPage = 1;
            loadSagas();
        }
    });

    let totalPages = $derived(Math.ceil(totalItems / pageSize));
</script>

<AdminLayout path="/admin/sagas">
    <div class="px-6 pb-6">
        <div class="mb-6">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">Saga Management</h1>
            <p class="text-fg-muted dark:text-dark-fg-muted">Monitor and debug distributed transactions</p>
        </div>

        <!-- Summary Statistics -->
        <div class="mb-6 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 sm:gap-3">
            {#each Object.entries(sagaStates) as [state, info]}
                {@const count = sagas.filter(s => s.state === state).length}
                {@const IconComponent = info.icon}
                <div class="card hover:shadow-lg transition-all duration-200 {info.bgColor}">
                    <div class="p-2 sm:p-3">
                        <div class="flex items-center justify-between gap-1">
                            <div class="min-w-0 flex-1">
                                <p class="text-[10px] sm:text-xs text-fg-muted uppercase tracking-wide mb-0.5 truncate">{info.label}</p>
                                <p class="text-base sm:text-lg lg:text-xl font-bold text-fg-default dark:text-dark-fg-default">{count}</p>
                            </div>
                            <IconComponent class="w-4 h-4 sm:w-5 sm:h-5 lg:w-6 lg:h-6 text-fg-muted" />
                        </div>
                    </div>
                </div>
            {/each}
        </div>

        <!-- Auto-refresh controls -->
        <div class="mb-6 card">
            <div class="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" bind:checked={autoRefresh} class="w-4 h-4 rounded border-border-default text-primary focus:ring-primary" />
                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Auto-refresh</span>
                </label>

                {#if autoRefresh}
                    <div class="flex items-center gap-2 flex-1 sm:flex-initial">
                        <label for="refresh-rate" class="text-xs sm:text-sm text-fg-muted">Every:</label>
                        <select id="refresh-rate" bind:value={refreshRate} class="form-select-standard">
                            <option value={5}>5 seconds</option>
                            <option value={10}>10 seconds</option>
                            <option value={30}>30 seconds</option>
                            <option value={60}>1 minute</option>
                        </select>
                    </div>
                {/if}

                <button onclick={loadSagas} class="sm:ml-auto btn btn-primary btn-sm w-full sm:w-auto" disabled={loading}>
                    {#if loading}
                        <Spinner size="small" color="white" className="-ml-1 mr-2" />Refreshing...
                    {:else}
                        <RefreshCw class="w-4 h-4 mr-1.5" />Refresh Now
                    {/if}
                </button>
            </div>
        </div>

        <!-- Filters -->
        <div class="mb-6 flex flex-col lg:grid lg:grid-cols-4 gap-3">
            <div>
                <label for="saga-search" class="block text-sm font-medium mb-2 text-fg-muted">Search</label>
                <input id="saga-search" type="text" bind:value={searchQuery} oninput={loadSagas}
                    placeholder="Search by ID, name, or error..." class="form-input-standard" />
            </div>
            <div>
                <label for="saga-state-filter" class="block text-sm font-medium mb-2 text-fg-muted">State</label>
                <select id="saga-state-filter" bind:value={stateFilter} class="form-select-standard">
                    <option value="">All States</option>
                    {#each Object.entries(sagaStates) as [value, state]}
                        <option value={value}>{state.label}</option>
                    {/each}
                </select>
            </div>
            <div>
                <label for="saga-execution-filter" class="block text-sm font-medium mb-2 text-fg-muted">Execution ID</label>
                <input id="saga-execution-filter" type="text" bind:value={executionIdFilter} oninput={loadSagas}
                    placeholder="Filter by execution ID..." class="form-input-standard" />
            </div>
            <div>
                <span class="block text-sm font-medium mb-2 text-fg-muted">Actions</span>
                <button onclick={clearFilters} class="w-full btn btn-secondary-outline">
                    <X class="w-4 h-4 mr-1.5" />Clear Filters
                </button>
            </div>
        </div>

        <!-- Sagas List -->
        <div class="bg-bg-default dark:bg-dark-bg-default rounded-lg shadow overflow-hidden">
            {#if loading && sagas.length === 0}
                <div class="p-8 text-center">
                    <Spinner size="xlarge" className="mx-auto mb-4" />
                    <p class="text-fg-muted">Loading sagas...</p>
                </div>
            {:else if sagas.length === 0}
                <div class="p-8 text-center text-fg-muted">No sagas found</div>
            {:else}
                <!-- Mobile Card View -->
                <div class="block lg:hidden">
                    {#each sagas as saga}
                        <div class="p-4 border-b border-border-default dark:border-dark-border-default hover:bg-bg-alt">
                            <div class="flex justify-between items-start mb-2">
                                <div class="flex-1 min-w-0 mr-2">
                                    <div class="font-medium text-sm">{saga.saga_name}</div>
                                    <div class="text-xs text-fg-muted mt-1">ID: {saga.saga_id.slice(0, 12)}...</div>
                                </div>
                                <span class="badge {getStateInfo(saga.state).color}">
                                    {getStateInfo(saga.state).label}
                                    {#if saga.retry_count > 0}<span class="ml-1">({saga.retry_count})</span>{/if}
                                </span>
                            </div>
                            <div class="grid grid-cols-2 gap-2 text-xs mb-2">
                                <div>
                                    <span class="text-fg-muted">Started:</span>
                                    <div>{formatTimestamp(saga.created_at)}</div>
                                </div>
                                <div>
                                    <span class="text-fg-muted">Duration:</span>
                                    <div>{formatDurationBetween(saga.created_at, saga.completed_at || saga.updated_at)}</div>
                                </div>
                            </div>
                            <div class="mb-2">
                                <div class="flex items-center justify-between mb-1">
                                    <span class="text-xs text-fg-muted">Progress: {saga.completed_steps.length} steps</span>
                                    <span class="text-xs text-fg-muted">{Math.round(getProgressPercentage(saga))}%</span>
                                </div>
                                <div class="progress-container"><div class="progress-bar" style="width: {getProgressPercentage(saga)}%"></div></div>
                            </div>
                            <div class="flex gap-2">
                                <button onclick={() => loadExecutionSagas(saga.execution_id)} class="flex-1 btn btn-sm btn-secondary-outline">Execution</button>
                                <button onclick={() => loadSagaDetails(saga.saga_id)} class="flex-1 btn btn-sm btn-primary">View Details</button>
                            </div>
                        </div>
                    {/each}
                </div>

                <!-- Desktop Table View -->
                <div class="hidden lg:block overflow-x-auto">
                    <table class="table">
                        <thead class="table-header">
                            <tr>
                                <th class="table-header-cell">Saga</th>
                                <th class="table-header-cell">State</th>
                                <th class="table-header-cell">Progress</th>
                                <th class="table-header-cell">Started</th>
                                <th class="table-header-cell">Duration</th>
                                <th class="table-header-cell text-center">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="table-body">
                            {#each sagas as saga}
                                <tr class="table-row">
                                    <td class="table-cell">
                                        <div class="font-medium">{saga.saga_name}</div>
                                        <div class="text-sm text-fg-muted">ID: {saga.saga_id.slice(0, 8)}...</div>
                                        <button onclick={() => loadExecutionSagas(saga.execution_id)} class="text-xs text-primary hover:text-primary-dark">
                                            Execution: {saga.execution_id.slice(0, 8)}...
                                        </button>
                                    </td>
                                    <td class="table-cell">
                                        <span class="badge {getStateInfo(saga.state).color}">{getStateInfo(saga.state).label}</span>
                                        {#if saga.retry_count > 0}<span class="ml-2 text-xs text-fg-muted">(Retry: {saga.retry_count})</span>{/if}
                                    </td>
                                    <td class="table-cell">
                                        <div class="w-32">
                                            <div class="flex items-center gap-2">
                                                <div class="flex-1 progress-container"><div class="progress-bar" style="width: {getProgressPercentage(saga)}%"></div></div>
                                                <span class="text-xs text-fg-muted">{saga.completed_steps.length}</span>
                                            </div>
                                            {#if saga.current_step}<div class="text-xs text-fg-muted mt-1 truncate">Current: {saga.current_step}</div>{/if}
                                        </div>
                                    </td>
                                    <td class="table-cell text-sm">{formatTimestamp(saga.created_at)}</td>
                                    <td class="table-cell text-sm">{formatDurationBetween(saga.created_at, saga.completed_at || saga.updated_at)}</td>
                                    <td class="table-cell text-center">
                                        <button onclick={() => loadSagaDetails(saga.saga_id)} class="text-primary hover:text-primary-dark">View Details</button>
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>

                <!-- Pagination -->
                {#if totalItems > 0}
                    <div class="p-4 border-t divider">
                        <Pagination {currentPage} {totalPages} {totalItems} {pageSize}
                            onPageChange={handlePageChange} onPageSizeChange={handlePageSizeChange} itemName="sagas" />
                    </div>
                {/if}
            {/if}
        </div>
    </div>
</AdminLayout>

<!-- Saga Detail Modal -->
{#if showDetailModal && selectedSaga}
<Modal open={showDetailModal} title="Saga Details" onClose={() => showDetailModal = false} size="lg">
    {#snippet children()}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
            <div>
                <h3 class="font-semibold mb-3">Basic Information</h3>
                <dl class="space-y-2 text-sm">
                    <div><dt class="text-fg-muted">Saga ID</dt><dd class="font-mono">{selectedSaga.saga_id}</dd></div>
                    <div><dt class="text-fg-muted">Saga Name</dt><dd class="font-medium">{selectedSaga.saga_name}</dd></div>
                    <div><dt class="text-fg-muted">Execution ID</dt>
                        <dd><button onclick={() => { showDetailModal = false; loadExecutionSagas(selectedSaga.execution_id); }} class="text-primary hover:text-primary-dark font-mono">{selectedSaga.execution_id}</button></dd>
                    </div>
                    <div><dt class="text-fg-muted">State</dt><dd><span class="badge {getStateInfo(selectedSaga.state).color}">{getStateInfo(selectedSaga.state).label}</span></dd></div>
                    <div><dt class="text-fg-muted">Retry Count</dt><dd>{selectedSaga.retry_count}</dd></div>
                </dl>
            </div>
            <div>
                <h3 class="font-semibold mb-3">Timing Information</h3>
                <dl class="space-y-2 text-sm">
                    <div><dt class="text-fg-muted">Created At</dt><dd>{formatTimestamp(selectedSaga.created_at)}</dd></div>
                    <div><dt class="text-fg-muted">Updated At</dt><dd>{formatTimestamp(selectedSaga.updated_at)}</dd></div>
                    <div><dt class="text-fg-muted">Completed At</dt><dd>{formatTimestamp(selectedSaga.completed_at)}</dd></div>
                    <div><dt class="text-fg-muted">Duration</dt><dd>{formatDurationBetween(selectedSaga.created_at, selectedSaga.completed_at || selectedSaga.updated_at)}</dd></div>
                </dl>
            </div>
        </div>

        <div class="mt-6">
            <h3 class="font-semibold mb-3">Execution Steps</h3>

            {#if selectedSaga.saga_name === 'execution_saga'}
                <div class="mb-4 p-4 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg overflow-x-auto">
                    <div class="flex items-start justify-between gap-0 min-w-[600px] pb-2">
                        {#each executionSagaSteps as step, index}
                            {@const isCompleted = selectedSaga.completed_steps.includes(step.name)}
                            {@const isCompensated = step.compensation && selectedSaga.compensated_steps.includes(step.compensation)}
                            {@const isCurrent = selectedSaga.current_step === step.name}
                            {@const isFailed = selectedSaga.state === 'failed' && isCurrent}

                            <div class="flex flex-col items-center flex-1 relative">
                                <div class="flex items-center w-full relative h-12">
                                    <div class="flex-1 flex items-center justify-end">
                                        {#if index > 0}
                                            <div class="h-0.5 w-full {selectedSaga.completed_steps.includes(executionSagaSteps[index - 1].name) && (isCompleted || isCompensated) ? 'bg-green-400' : 'bg-neutral-300 dark:bg-neutral-600'}"></div>
                                        {/if}
                                    </div>
                                    <div class="relative z-10 mx-1">
                                        <div class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold border-2
                                            {isCompleted ? 'bg-green-100 text-green-600 border-green-300 dark:bg-green-900/30 dark:border-green-600' :
                                             isCompensated ? 'bg-yellow-100 text-yellow-600 border-yellow-300' :
                                             isCurrent ? 'bg-blue-100 text-blue-600 border-blue-300 animate-pulse' :
                                             isFailed ? 'bg-red-100 text-red-600 border-red-300' :
                                             'bg-neutral-100 text-neutral-400 border-neutral-300 dark:bg-neutral-800'}">
                                            {#if isCompleted}<Check class="w-5 h-5" />
                                            {:else if isCompensated}<Undo2 class="w-4 h-4" />
                                            {:else if isCurrent}<div class="w-2 h-2 bg-current rounded-full"></div>
                                            {:else if isFailed}<X class="w-5 h-5" />
                                            {:else}<span class="text-sm font-bold">{index + 1}</span>{/if}
                                        </div>
                                    </div>
                                    <div class="flex-1 flex items-center justify-start">
                                        {#if index < executionSagaSteps.length - 1}
                                            <div class="h-0.5 w-full {isCompleted && selectedSaga.completed_steps.includes(executionSagaSteps[index + 1].name) ? 'bg-green-400' : 'bg-neutral-300 dark:bg-neutral-600'}"></div>
                                        {/if}
                                    </div>
                                </div>
                                <div class="mt-2 text-xs font-medium text-center px-1">
                                    {step.label}
                                    {#if step.compensation && isCompensated}<div class="text-xs text-yellow-600 mt-1">(compensated)</div>{/if}
                                </div>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if selectedSaga.current_step}
                <div class="mb-4 p-3 alert alert-info"><span class="font-medium">Current Step:</span> {selectedSaga.current_step}</div>
            {/if}

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                    <h4 class="text-sm font-medium mb-2 text-green-600">Completed ({selectedSaga.completed_steps.length})</h4>
                    {#if selectedSaga.completed_steps.length > 0}
                        <ul class="space-y-1">{#each selectedSaga.completed_steps as step}<li class="flex items-center gap-2 text-sm"><Check class="w-4 h-4 text-green-500" />{step}</li>{/each}</ul>
                    {:else}<p class="text-sm text-fg-muted">No completed steps</p>{/if}
                </div>
                <div>
                    <h4 class="text-sm font-medium mb-2 text-yellow-600">Compensated ({selectedSaga.compensated_steps.length})</h4>
                    {#if selectedSaga.compensated_steps.length > 0}
                        <ul class="space-y-1">{#each selectedSaga.compensated_steps as step}<li class="flex items-center gap-2 text-sm"><Undo2 class="w-4 h-4 text-yellow-500" />{step}</li>{/each}</ul>
                    {:else}<p class="text-sm text-fg-muted">No compensated steps</p>{/if}
                </div>
            </div>
        </div>

        {#if selectedSaga.error_message}
            <div class="mt-6">
                <h3 class="font-semibold mb-3 text-red-600">Error Information</h3>
                <div class="p-4 alert alert-danger"><pre class="text-sm whitespace-pre-wrap">{selectedSaga.error_message}</pre></div>
            </div>
        {/if}

        {#if selectedSaga.context_data && Object.keys(selectedSaga.context_data).length > 0}
            <div class="mt-6">
                <h3 class="font-semibold mb-3">Context Data</h3>
                <div class="p-4 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
                    <pre class="text-sm overflow-x-auto">{JSON.stringify(selectedSaga.context_data, null, 2)}</pre>
                </div>
            </div>
        {/if}
    {/snippet}
</Modal>
{/if}
