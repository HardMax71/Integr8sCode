<script>
    import { onMount, onDestroy } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let loading = true;
    let sagas = [];
    let selectedSaga = null;
    let showDetailModal = false;
    let refreshInterval = null;
    let autoRefresh = true;
    let refreshRate = 5; // seconds
    
    // Filters
    let stateFilter = '';
    let executionIdFilter = '';
    let searchQuery = '';
    
    // Pagination
    let currentPage = 1;
    let itemsPerPage = 20;
    let totalItems = 0;
    
    // Saga states
    const sagaStates = {
        created: { label: 'Created', color: 'bg-gray-100 text-gray-800', icon: '🔵' },
        running: { label: 'Running', color: 'bg-blue-100 text-blue-800', icon: '🔄' },
        compensating: { label: 'Compensating', color: 'bg-yellow-100 text-yellow-800', icon: '⚠️' },
        completed: { label: 'Completed', color: 'bg-green-100 text-green-800', icon: '✅' },
        failed: { label: 'Failed', color: 'bg-red-100 text-red-800', icon: '❌' },
        timeout: { label: 'Timeout', color: 'bg-orange-100 text-orange-800', icon: '⏱️' }
    };
    
    // Execution saga steps
    const executionSagaSteps = [
        { name: 'validate_execution', label: 'Validate', compensation: null },
        { name: 'allocate_resources', label: 'Allocate Resources', compensation: 'release_resources' },
        { name: 'queue_execution', label: 'Queue Execution', compensation: 'remove_from_queue' },
        { name: 'create_pod', label: 'Create Pod', compensation: 'delete_pod' },
        { name: 'monitor_execution', label: 'Monitor', compensation: null }
    ];
    
    async function loadSagas() {
        try {
            loading = true;
            
            const params = new URLSearchParams();
            if (stateFilter) params.append('state', stateFilter);
            params.append('limit', itemsPerPage);
            params.append('offset', (currentPage - 1) * itemsPerPage);
            
            const response = await api.get(`/api/v1/sagas?${params}`);
            sagas = response.sagas;
            totalItems = response.total;
            
            // Filter by execution ID and search query on client side
            if (executionIdFilter) {
                sagas = sagas.filter(s => s.execution_id.includes(executionIdFilter));
            }
            if (searchQuery) {
                const query = searchQuery.toLowerCase();
                sagas = sagas.filter(s => 
                    s.saga_id.toLowerCase().includes(query) ||
                    s.saga_name.toLowerCase().includes(query) ||
                    s.execution_id.toLowerCase().includes(query) ||
                    (s.error_message && s.error_message.toLowerCase().includes(query))
                );
            }
        } catch (error) {
            console.error('Failed to load sagas:', error);
            addNotification('Failed to load sagas', 'error');
        } finally {
            loading = false;
        }
    }
    
    async function loadSagaDetails(sagaId) {
        try {
            const response = await api.get(`/api/v1/sagas/${sagaId}`);
            selectedSaga = response;
            showDetailModal = true;
        } catch (error) {
            console.error('Failed to load saga details:', error);
            addNotification('Failed to load saga details', 'error');
        }
    }
    
    async function loadExecutionSagas(executionId) {
        try {
            loading = true;
            const response = await api.get(`/api/v1/sagas/execution/${executionId}`);
            sagas = response.sagas;
            totalItems = response.total;
            executionIdFilter = executionId;
        } catch (error) {
            console.error('Failed to load execution sagas:', error);
            addNotification('Failed to load execution sagas', 'error');
        } finally {
            loading = false;
        }
    }
    
    function formatDate(dateString) {
        if (!dateString) return 'N/A';
        return new Date(dateString).toLocaleString();
    }
    
    function formatDuration(startDate, endDate) {
        if (!startDate || !endDate) return 'N/A';
        const start = new Date(startDate);
        const end = new Date(endDate);
        const duration = end - start;
        
        if (duration < 1000) return `${duration}ms`;
        if (duration < 60000) return `${(duration / 1000).toFixed(1)}s`;
        if (duration < 3600000) return `${Math.floor(duration / 60000)}m ${Math.floor((duration % 60000) / 1000)}s`;
        return `${Math.floor(duration / 3600000)}h ${Math.floor((duration % 3600000) / 60000)}m`;
    }
    
    function getStateInfo(state) {
        return sagaStates[state] || { label: state, color: 'bg-gray-100 text-gray-800' };
    }
    
    function getProgressPercentage(saga) {
        if (!saga.completed_steps || saga.completed_steps.length === 0) return 0;
        // Estimate total steps based on saga name
        const totalSteps = saga.saga_name === 'execution_saga' ? 5 : 3;
        return Math.min(100, (saga.completed_steps.length / totalSteps) * 100);
    }
    
    function setupAutoRefresh() {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
        
        if (autoRefresh) {
            refreshInterval = setInterval(() => {
                loadSagas();
            }, refreshRate * 1000);
        }
    }
    
    function handlePageChange(page) {
        currentPage = page;
        loadSagas();
    }
    
    function clearFilters() {
        stateFilter = '';
        executionIdFilter = '';
        searchQuery = '';
        currentPage = 1;
        loadSagas();
    }
    
    onMount(() => {
        loadSagas();
        setupAutoRefresh();
    });
    
    onDestroy(() => {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
    });
    
    $: if (autoRefresh || refreshRate) {
        setupAutoRefresh();
    }
    
    $: if (stateFilter !== undefined) {
        currentPage = 1;
        loadSagas();
    }
    
    $: totalPages = Math.ceil(totalItems / itemsPerPage);
</script>

<AdminLayout path="/admin/sagas">
    <div class="px-6 pb-6">
        <div class="mb-6">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">
                Saga Management
            </h1>
            <p class="text-fg-muted dark:text-dark-fg-muted">
                Monitor and debug distributed transactions across the system
            </p>
        </div>
        
        <!-- Summary Statistics -->
        <div class="mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
            {#each Object.entries(sagaStates) as [state, info]}
                {@const count = sagas.filter(s => s.state === state).length}
                <div class="p-4 bg-bg-default dark:bg-dark-bg-default rounded-lg shadow">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm text-fg-muted">{info.label}</p>
                            <p class="text-2xl font-bold">{count}</p>
                        </div>
                        <span class="text-2xl">{info.icon}</span>
                    </div>
                </div>
            {/each}
        </div>
        
        <!-- Auto-refresh controls -->
        <div class="mb-6 flex items-center gap-4 p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
            <label class="flex items-center gap-2">
                <input
                    type="checkbox"
                    bind:checked={autoRefresh}
                    class="rounded border-gray-300"
                />
                <span class="text-sm">Auto-refresh</span>
            </label>
            {#if autoRefresh}
                <div class="flex items-center gap-2">
                    <label class="text-sm">Every:</label>
                    <select
                        bind:value={refreshRate}
                        class="px-3 py-1 rounded border border-border-default dark:border-dark-border-default bg-bg-default dark:bg-dark-bg-default"
                    >
                        <option value={5}>5 seconds</option>
                        <option value={10}>10 seconds</option>
                        <option value={30}>30 seconds</option>
                        <option value={60}>1 minute</option>
                    </select>
                </div>
            {/if}
            <button
                on:click={loadSagas}
                class="ml-auto px-4 py-2 bg-primary text-white rounded hover:bg-primary-dark transition-colors"
                disabled={loading}
            >
                {loading ? 'Refreshing...' : 'Refresh Now'}
            </button>
        </div>
        
        <!-- Filters -->
        <div class="mb-6 grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
                <label class="block text-sm font-medium mb-2">Search</label>
                <input
                    type="text"
                    bind:value={searchQuery}
                    on:input={loadSagas}
                    placeholder="Search by ID, name, or error..."
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                />
            </div>
            
            <div>
                <label class="block text-sm font-medium mb-2">State</label>
                <select
                    bind:value={stateFilter}
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                >
                    <option value="">All States</option>
                    {#each Object.entries(sagaStates) as [value, state]}
                        <option value={value}>{state.label}</option>
                    {/each}
                </select>
            </div>
            
            <div>
                <label class="block text-sm font-medium mb-2">Execution ID</label>
                <input
                    type="text"
                    bind:value={executionIdFilter}
                    on:input={loadSagas}
                    placeholder="Filter by execution ID..."
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                />
            </div>
            
            <div class="flex items-end">
                <button
                    on:click={clearFilters}
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg hover:bg-bg-alt dark:hover:bg-dark-bg-alt transition-colors"
                >
                    Clear Filters
                </button>
            </div>
        </div>
        
        <!-- Sagas List -->
        <div class="bg-bg-default dark:bg-dark-bg-default rounded-lg shadow">
            {#if loading && sagas.length === 0}
                <div class="p-8 text-center">
                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
                    <p class="text-fg-muted">Loading sagas...</p>
                </div>
            {:else if sagas.length === 0}
                <div class="p-8 text-center text-fg-muted">
                    No sagas found
                </div>
            {:else}
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead>
                            <tr class="border-b border-border-default dark:border-dark-border-default">
                                <th class="px-4 py-3 text-left">Saga</th>
                                <th class="px-4 py-3 text-left">State</th>
                                <th class="px-4 py-3 text-left">Progress</th>
                                <th class="px-4 py-3 text-left">Started</th>
                                <th class="px-4 py-3 text-left">Duration</th>
                                <th class="px-4 py-3 text-center">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each sagas as saga}
                                <tr class="border-b border-border-default dark:border-dark-border-default hover:bg-bg-alt dark:hover:bg-dark-bg-alt">
                                    <td class="px-4 py-3">
                                        <div>
                                            <div class="font-medium">{saga.saga_name}</div>
                                            <div class="text-sm text-fg-muted">
                                                ID: {saga.saga_id.slice(0, 8)}...
                                            </div>
                                            <button
                                                on:click={() => loadExecutionSagas(saga.execution_id)}
                                                class="text-xs text-primary hover:text-primary-dark"
                                            >
                                                Execution: {saga.execution_id.slice(0, 8)}...
                                            </button>
                                        </div>
                                    </td>
                                    <td class="px-4 py-3">
                                        <span class="px-2 py-1 text-xs rounded-full {getStateInfo(saga.state).color}">
                                            {getStateInfo(saga.state).label}
                                        </span>
                                        {#if saga.retry_count > 0}
                                            <span class="ml-2 text-xs text-fg-muted">
                                                (Retry: {saga.retry_count})
                                            </span>
                                        {/if}
                                    </td>
                                    <td class="px-4 py-3">
                                        <div class="w-32">
                                            <div class="flex items-center gap-2">
                                                <div class="flex-1 bg-gray-200 rounded-full h-2">
                                                    <div 
                                                        class="bg-primary h-2 rounded-full transition-all duration-300"
                                                        style="width: {getProgressPercentage(saga)}%"
                                                    ></div>
                                                </div>
                                                <span class="text-xs text-fg-muted">
                                                    {saga.completed_steps.length}
                                                </span>
                                            </div>
                                            {#if saga.current_step}
                                                <div class="text-xs text-fg-muted mt-1 truncate">
                                                    Current: {saga.current_step}
                                                </div>
                                            {/if}
                                        </div>
                                    </td>
                                    <td class="px-4 py-3 text-sm">
                                        {formatDate(saga.created_at)}
                                    </td>
                                    <td class="px-4 py-3 text-sm">
                                        {formatDuration(saga.created_at, saga.completed_at || saga.updated_at)}
                                    </td>
                                    <td class="px-4 py-3 text-center">
                                        <button
                                            on:click={() => loadSagaDetails(saga.saga_id)}
                                            class="text-primary hover:text-primary-dark"
                                        >
                                            View Details
                                        </button>
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
                
                <!-- Pagination -->
                {#if totalPages > 1}
                    <div class="p-4 flex items-center justify-between border-t border-border-default dark:border-dark-border-default">
                        <div class="text-sm text-fg-muted">
                            Showing {(currentPage - 1) * itemsPerPage + 1} to {Math.min(currentPage * itemsPerPage, totalItems)} of {totalItems} sagas
                        </div>
                        <div class="flex gap-2">
                            <button
                                on:click={() => handlePageChange(currentPage - 1)}
                                disabled={currentPage === 1}
                                class="px-3 py-1 border rounded {currentPage === 1 ? 'opacity-50 cursor-not-allowed' : 'hover:bg-bg-alt'}"
                            >
                                Previous
                            </button>
                            {#each Array(Math.min(5, totalPages)) as _, i}
                                {@const page = currentPage > 3 ? currentPage - 2 + i : i + 1}
                                {#if page > 0 && page <= totalPages}
                                    <button
                                        on:click={() => handlePageChange(page)}
                                        class="px-3 py-1 border rounded {page === currentPage ? 'bg-primary text-white' : 'hover:bg-bg-alt'}"
                                    >
                                        {page}
                                    </button>
                                {/if}
                            {/each}
                            <button
                                on:click={() => handlePageChange(currentPage + 1)}
                                disabled={currentPage === totalPages}
                                class="px-3 py-1 border rounded {currentPage === totalPages ? 'opacity-50 cursor-not-allowed' : 'hover:bg-bg-alt'}"
                            >
                                Next
                            </button>
                        </div>
                    </div>
                {/if}
            {/if}
        </div>
    </div>
</AdminLayout>

<!-- Saga Detail Modal -->
{#if showDetailModal && selectedSaga}
    <div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
        <div class="bg-bg-default dark:bg-dark-bg-default rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
            <div class="p-6 border-b border-border-default dark:border-dark-border-default flex justify-between items-center">
                <h2 class="text-xl font-semibold">Saga Details</h2>
                <button
                    on:click={() => showDetailModal = false}
                    class="text-fg-muted hover:text-fg-default"
                >
                    ✕
                </button>
            </div>
            
            <div class="p-6 overflow-y-auto max-h-[calc(90vh-120px)]">
                <div class="grid grid-cols-2 gap-6">
                    <!-- Basic Info -->
                    <div>
                        <h3 class="font-semibold mb-3">Basic Information</h3>
                        <dl class="space-y-2 text-sm">
                            <div>
                                <dt class="text-fg-muted">Saga ID</dt>
                                <dd class="font-mono">{selectedSaga.saga_id}</dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">Saga Name</dt>
                                <dd class="font-medium">{selectedSaga.saga_name}</dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">Execution ID</dt>
                                <dd class="font-mono">
                                    <button
                                        on:click={() => {
                                            showDetailModal = false;
                                            loadExecutionSagas(selectedSaga.execution_id);
                                        }}
                                        class="text-primary hover:text-primary-dark"
                                    >
                                        {selectedSaga.execution_id}
                                    </button>
                                </dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">State</dt>
                                <dd>
                                    <span class="px-2 py-1 text-xs rounded-full {getStateInfo(selectedSaga.state).color}">
                                        {getStateInfo(selectedSaga.state).label}
                                    </span>
                                </dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">Retry Count</dt>
                                <dd>{selectedSaga.retry_count}</dd>
                            </div>
                        </dl>
                    </div>
                    
                    <!-- Timing Info -->
                    <div>
                        <h3 class="font-semibold mb-3">Timing Information</h3>
                        <dl class="space-y-2 text-sm">
                            <div>
                                <dt class="text-fg-muted">Created At</dt>
                                <dd>{formatDate(selectedSaga.created_at)}</dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">Updated At</dt>
                                <dd>{formatDate(selectedSaga.updated_at)}</dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">Completed At</dt>
                                <dd>{formatDate(selectedSaga.completed_at)}</dd>
                            </div>
                            <div>
                                <dt class="text-fg-muted">Total Duration</dt>
                                <dd>{formatDuration(selectedSaga.created_at, selectedSaga.completed_at || selectedSaga.updated_at)}</dd>
                            </div>
                        </dl>
                    </div>
                </div>
                
                <!-- Steps Information -->
                <div class="mt-6">
                    <h3 class="font-semibold mb-3">Execution Steps</h3>
                    
                    {#if selectedSaga.saga_name === 'execution_saga'}
                        <div class="mb-4 p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                            <div class="flex items-center justify-between gap-2 overflow-x-auto">
                                {#each executionSagaSteps as step, index}
                                    {@const isCompleted = selectedSaga.completed_steps.includes(step.name)}
                                    {@const isCompensated = selectedSaga.compensated_steps.includes(step.compensation) && step.compensation}
                                    {@const isCurrent = selectedSaga.current_step === step.name}
                                    {@const isFailed = selectedSaga.state === 'failed' && selectedSaga.current_step === step.name}
                                    
                                    <div class="flex items-center">
                                        <div class="text-center">
                                            <div class="relative">
                                                <div class="w-12 h-12 rounded-full flex items-center justify-center text-lg
                                                    {isCompleted ? 'bg-green-100 text-green-600' : 
                                                     isCompensated ? 'bg-yellow-100 text-yellow-600' :
                                                     isCurrent ? 'bg-blue-100 text-blue-600 animate-pulse' :
                                                     isFailed ? 'bg-red-100 text-red-600' :
                                                     'bg-gray-100 text-gray-400'}">
                                                    {isCompleted ? '✓' : 
                                                     isCompensated ? '↩' :
                                                     isCurrent ? '•' :
                                                     isFailed ? '✗' :
                                                     index + 1}
                                                </div>
                                                {#if step.compensation && isCompensated}
                                                    <div class="absolute -bottom-6 left-0 right-0 text-xs text-yellow-600">
                                                        compensated
                                                    </div>
                                                {/if}
                                            </div>
                                            <div class="mt-2 text-xs font-medium max-w-[100px]">{step.label}</div>
                                        </div>
                                        {#if index < executionSagaSteps.length - 1}
                                            <div class="w-8 h-0.5 mx-1 
                                                {isCompleted && selectedSaga.completed_steps.includes(executionSagaSteps[index + 1].name) ? 'bg-green-400' : 'bg-gray-300'}">
                                            </div>
                                        {/if}
                                    </div>
                                {/each}
                            </div>
                        </div>
                    {/if}
                    
                    {#if selectedSaga.current_step}
                        <div class="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                            <div class="text-sm">
                                <span class="font-medium">Current Step:</span> {selectedSaga.current_step}
                            </div>
                        </div>
                    {/if}
                    
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <h4 class="text-sm font-medium mb-2 text-green-600">Completed Steps ({selectedSaga.completed_steps.length})</h4>
                            {#if selectedSaga.completed_steps.length > 0}
                                <ul class="space-y-1">
                                    {#each selectedSaga.completed_steps as step}
                                        <li class="flex items-center gap-2 text-sm">
                                            <span class="text-green-500">✓</span>
                                            <span>{step}</span>
                                        </li>
                                    {/each}
                                </ul>
                            {:else}
                                <p class="text-sm text-fg-muted">No completed steps</p>
                            {/if}
                        </div>
                        
                        <div>
                            <h4 class="text-sm font-medium mb-2 text-yellow-600">Compensated Steps ({selectedSaga.compensated_steps.length})</h4>
                            {#if selectedSaga.compensated_steps.length > 0}
                                <ul class="space-y-1">
                                    {#each selectedSaga.compensated_steps as step}
                                        <li class="flex items-center gap-2 text-sm">
                                            <span class="text-yellow-500">↩</span>
                                            <span>{step}</span>
                                        </li>
                                    {/each}
                                </ul>
                            {:else}
                                <p class="text-sm text-fg-muted">No compensated steps</p>
                            {/if}
                        </div>
                    </div>
                </div>
                
                <!-- Error Information -->
                {#if selectedSaga.error_message}
                    <div class="mt-6">
                        <h3 class="font-semibold mb-3 text-red-600">Error Information</h3>
                        <div class="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg">
                            <pre class="text-sm whitespace-pre-wrap text-red-800 dark:text-red-200">{selectedSaga.error_message}</pre>
                        </div>
                    </div>
                {/if}
                
                <!-- Context Data -->
                {#if selectedSaga.context_data && Object.keys(selectedSaga.context_data).length > 0}
                    <div class="mt-6">
                        <h3 class="font-semibold mb-3">Context Data</h3>
                        <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                            <pre class="text-sm overflow-x-auto">{JSON.stringify(selectedSaga.context_data, null, 2)}</pre>
                        </div>
                    </div>
                {/if}
            </div>
        </div>
    </div>
{/if}

<style>
    /* Custom scrollbar for modal */
    .overflow-y-auto::-webkit-scrollbar {
        width: 8px;
    }
    
    .overflow-y-auto::-webkit-scrollbar-track {
        background: var(--color-bg-alt);
    }
    
    .overflow-y-auto::-webkit-scrollbar-thumb {
        background: var(--color-border-default);
        border-radius: 4px;
    }
    
    .overflow-y-auto::-webkit-scrollbar-thumb:hover {
        background: var(--color-fg-muted);
    }
</style>