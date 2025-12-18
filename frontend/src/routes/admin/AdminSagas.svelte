<script>
    import { onMount, onDestroy } from 'svelte';
    import { api } from '../../lib/api';
    import { addToast } from '../../stores/toastStore';
    import AdminLayout from './AdminLayout.svelte';
    import Spinner from '../../components/Spinner.svelte';
    
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
    let itemsPerPage = 10;
    let totalItems = 0;
    
    // Saga states with SVG icons
    const sagaStates = {
        created: { 
            label: 'Created', 
            color: 'bg-gray-100 text-gray-800',
            bgColor: 'bg-gray-50 dark:bg-gray-900/20',
            iconColor: 'text-gray-600 dark:text-gray-400',
            icon: `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
            </svg>`
        },
        running: { 
            label: 'Running', 
            color: 'bg-blue-100 text-blue-800',
            bgColor: 'bg-blue-50 dark:bg-blue-900/20',
            iconColor: 'text-blue-600 dark:text-blue-400',
            icon: `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>`
        },
        compensating: { 
            label: 'Compensating', 
            color: 'bg-yellow-100 text-yellow-800',
            bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
            iconColor: 'text-yellow-600 dark:text-yellow-400',
            icon: `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>`
        },
        completed: { 
            label: 'Completed', 
            color: 'bg-green-100 text-green-800',
            bgColor: 'bg-green-50 dark:bg-green-900/20',
            iconColor: 'text-green-600 dark:text-green-400',
            icon: `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>`
        },
        failed: { 
            label: 'Failed', 
            color: 'bg-red-100 text-red-800',
            bgColor: 'bg-red-50 dark:bg-red-900/20',
            iconColor: 'text-red-600 dark:text-red-400',
            icon: `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>`
        },
        timeout: { 
            label: 'Timeout', 
            color: 'bg-orange-100 text-orange-800',
            bgColor: 'bg-orange-50 dark:bg-orange-900/20',
            iconColor: 'text-orange-600 dark:text-orange-400',
            icon: `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>`
        }
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
            
            const response = await api.get(`/api/v1/sagas/?${params}`);
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
            addToast('Failed to load sagas', 'error');
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
            addToast('Failed to load saga details', 'error');
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
            addToast('Failed to load execution sagas', 'error');
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
        <div class="mb-6 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 sm:gap-3">
            {#each Object.entries(sagaStates) as [state, info]}
                {@const count = sagas.filter(s => s.state === state).length}
                <div class="card hover:shadow-lg transition-all duration-200 {info.bgColor} min-w-0 overflow-hidden">
                    <div class="p-2 sm:p-3">
                        <div class="flex items-center justify-between gap-1">
                            <div class="min-w-0 flex-1">
                                <p class="text-[10px] sm:text-xs text-fg-muted dark:text-dark-fg-muted uppercase tracking-wide mb-0.5 truncate">
                                    {info.label}
                                </p>
                                <p class="text-base sm:text-lg lg:text-xl font-bold text-fg-default dark:text-dark-fg-default">
                                    {count}
                                </p>
                            </div>
                            <div class="{info.iconColor} w-4 h-4 sm:w-5 sm:h-5 lg:w-6 lg:h-6 shrink-0">
                                {@html info.icon}
                            </div>
                        </div>
                    </div>
                </div>
            {/each}
        </div>
        
        <!-- Auto-refresh controls -->
        <div class="mb-6 card">
            <div class="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                <label class="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        bind:checked={autoRefresh}
                        class="w-4 h-4 rounded border-border-default dark:border-dark-border-default text-primary focus:ring-primary focus:ring-2"
                    />
                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Auto-refresh</span>
                </label>
                
                {#if autoRefresh}
                    <div class="flex items-center gap-2 flex-1 sm:flex-initial">
                        <label for="refresh-rate" class="text-xs sm:text-sm text-fg-muted dark:text-dark-fg-muted">Every:</label>
                        <select
                            id="refresh-rate"
                            bind:value={refreshRate}
                            class="flex-1 sm:min-w-[140px] px-3 py-1.5 pr-8 rounded-lg border border-border-default dark:border-dark-border-default
                                   bg-bg-default dark:bg-dark-bg-default text-fg-default dark:text-dark-fg-default
                                   focus:outline-hidden focus:ring-2 focus:ring-primary focus:border-primary
                                   appearance-none bg-no-repeat bg-[length:16px] bg-[right_0.5rem_center]"
                            style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 fill=%22none%22 viewBox=%220 0 20 20%22><path stroke=%22%236b7280%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22 stroke-width=%221.5%22 d=%22M6 8l4 4 4-4%22/></svg>');"
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
                    class="sm:ml-auto btn btn-primary btn-sm w-full sm:w-auto"
                    disabled={loading}
                >
                    {#if loading}
                        <Spinner size="small" color="white" className="-ml-1 mr-2" />
                        Refreshing...
                    {:else}
                        <svg class="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Refresh Now
                    {/if}
                </button>
            </div>
        </div>
        
        <!-- Filters -->
        <div class="mb-6 flex flex-col lg:grid lg:grid-cols-4 gap-3">
            <div class="lg:col-span-1">
                <label for="saga-search" class="block text-sm font-medium mb-2 text-fg-muted dark:text-dark-fg-muted">Search</label>
                <input
                    id="saga-search"
                    type="text"
                    bind:value={searchQuery}
                    on:input={loadSagas}
                    placeholder="Search by ID, name, or error..."
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg
                           bg-bg-default dark:bg-dark-bg-default text-fg-default dark:text-dark-fg-default
                           placeholder-fg-subtle dark:placeholder-dark-fg-subtle
                           focus:outline-hidden focus:ring-2 focus:ring-primary focus:border-primary"
                />
            </div>

            <div class="lg:col-span-1">
                <label for="saga-state-filter" class="block text-sm font-medium mb-2 text-fg-muted dark:text-dark-fg-muted">State</label>
                <select
                    id="saga-state-filter"
                    bind:value={stateFilter}
                    on:change={loadSagas}
                    class="w-full px-4 py-2 pr-10 border border-border-default dark:border-dark-border-default rounded-lg
                           bg-bg-default dark:bg-dark-bg-default text-fg-default dark:text-dark-fg-default
                           focus:outline-hidden focus:ring-2 focus:ring-primary focus:border-primary
                           appearance-none bg-no-repeat bg-[length:16px] bg-[right_0.75rem_center]"
                    style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 fill=%22none%22 viewBox=%220 0 20 20%22><path stroke=%22%236b7280%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22 stroke-width=%221.5%22 d=%22M6 8l4 4 4-4%22/></svg>');"
                >
                    <option value="">All States</option>
                    {#each Object.entries(sagaStates) as [value, state]}
                        <option value={value}>{state.label}</option>
                    {/each}
                </select>
            </div>

            <div class="lg:col-span-1">
                <label for="saga-execution-filter" class="block text-sm font-medium mb-2 text-fg-muted dark:text-dark-fg-muted">Execution ID</label>
                <input
                    id="saga-execution-filter"
                    type="text"
                    bind:value={executionIdFilter}
                    on:input={loadSagas}
                    placeholder="Filter by execution ID..."
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg
                           bg-bg-default dark:bg-dark-bg-default text-fg-default dark:text-dark-fg-default
                           placeholder-fg-subtle dark:placeholder-dark-fg-subtle
                           focus:outline-hidden focus:ring-2 focus:ring-primary focus:border-primary"
                />
            </div>
            
            <div class="lg:col-span-1">
                <span class="block text-sm font-medium mb-2 text-fg-muted dark:text-dark-fg-muted">Actions</span>
                <button
                    on:click={clearFilters}
                    class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg 
                           bg-bg-default dark:bg-dark-bg-default text-fg-default dark:text-dark-fg-default
                           hover:bg-bg-alt dark:hover:bg-dark-bg-alt transition-colors
                           focus:outline-hidden focus:ring-2 focus:ring-primary focus:border-primary"
                >
                    <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    Clear Filters
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
                <div class="p-8 text-center text-fg-muted">
                    No sagas found
                </div>
            {:else}
                <!-- Mobile Card View (shown on small screens) -->
                <div class="block lg:hidden">
                    {#each sagas as saga}
                        <div class="p-4 border-b border-border-default dark:border-dark-border-default hover:bg-bg-alt dark:hover:bg-dark-bg-alt">
                            <div class="flex justify-between items-start mb-2">
                                <div class="flex-1 min-w-0 mr-2">
                                    <div class="font-medium text-sm">{saga.saga_name}</div>
                                    <div class="text-xs text-fg-muted mt-1">
                                        ID: {saga.saga_id.slice(0, 12)}...
                                    </div>
                                </div>
                                <span class="px-2 py-1 text-xs rounded-full {getStateInfo(saga.state).color} whitespace-nowrap">
                                    {getStateInfo(saga.state).label}
                                    {#if saga.retry_count > 0}
                                        <span class="ml-1">({saga.retry_count})</span>
                                    {/if}
                                </span>
                            </div>
                            
                            <div class="grid grid-cols-2 gap-2 text-xs mb-2">
                                <div>
                                    <span class="text-fg-muted">Started:</span>
                                    <div class="text-fg-default">{new Date(saga.created_at).toLocaleDateString()}</div>
                                    <div class="text-fg-default">{new Date(saga.created_at).toLocaleTimeString()}</div>
                                </div>
                                <div>
                                    <span class="text-fg-muted">Duration:</span>
                                    <div class="text-fg-default">{formatDuration(saga.created_at, saga.completed_at || saga.updated_at)}</div>
                                </div>
                            </div>
                            
                            <div class="mb-2">
                                <div class="flex items-center justify-between mb-1">
                                    <span class="text-xs text-fg-muted">Progress: {saga.completed_steps.length} steps</span>
                                    <span class="text-xs text-fg-muted">{Math.round(getProgressPercentage(saga))}%</span>
                                </div>
                                <div class="bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                                    <div 
                                        class="bg-primary h-2 rounded-full transition-all duration-300"
                                        style="width: {getProgressPercentage(saga)}%"
                                    ></div>
                                </div>
                                {#if saga.current_step}
                                    <div class="text-xs text-fg-muted mt-1 truncate">
                                        Current: {saga.current_step}
                                    </div>
                                {/if}
                            </div>
                            
                            <div class="flex gap-2">
                                <button
                                    on:click={() => loadExecutionSagas(saga.execution_id)}
                                    class="flex-1 text-xs py-1.5 px-2 rounded border border-border-default dark:border-dark-border-default text-primary hover:bg-primary hover:text-white transition-colors"
                                >
                                    Execution
                                </button>
                                <button
                                    on:click={() => loadSagaDetails(saga.saga_id)}
                                    class="flex-1 text-xs py-1.5 px-2 rounded bg-primary text-white hover:bg-primary-dark transition-colors"
                                >
                                    View Details
                                </button>
                            </div>
                        </div>
                    {/each}
                </div>
                
                <!-- Desktop Table View (shown on large screens) -->
                <div class="hidden lg:block overflow-x-auto">
                    <table class="w-full divide-y divide-border-default dark:divide-dark-border-default">
                        <thead class="bg-neutral-50 dark:bg-neutral-900">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Saga</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">State</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Progress</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Started</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Duration</th>
                                <th class="px-4 py-3 text-center text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-bg-default dark:bg-dark-bg-default divide-y divide-border-default dark:divide-dark-border-default">
                            {#each sagas as saga}
                                <tr class="hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
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
                {#if totalItems > 0}
                    <div class="p-4 border-t divider">
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                            <!-- Left side container -->
                            <div class="flex items-center gap-4">
                                <!-- Page size selector -->
                                <div class="flex items-center gap-2">
                                    <label for="saga-page-size" class="text-sm text-fg-muted dark:text-dark-fg-muted">Show:</label>
                                    <select
                                        id="saga-page-size"
                                        bind:value={itemsPerPage}
                                        on:change={() => { currentPage = 1; loadSagas(); }}
                                        class="px-3 py-1.5 pr-8 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none cursor-pointer"
                                        style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 fill=%22none%22 viewBox=%220 0 20 20%22><path stroke=%22%236b7280%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22 stroke-width=%221.5%22 d=%22M6 8l4 4 4-4%22/></svg>'); background-repeat: no-repeat; background-position: right 0.5rem center; background-size: 16px;"
                                    >
                                        <option value={10}>10</option>
                                        <option value={25}>25</option>
                                        <option value={50}>50</option>
                                        <option value={100}>100</option>
                                    </select>
                                    <span class="text-sm text-fg-muted dark:text-dark-fg-muted">per page</span>
                                </div>
                                
                                <!-- Pagination controls -->
                                {#if totalPages > 1}
                                <div class="flex items-center gap-1">
                                <!-- First page -->
                                <button
                                    on:click={() => { currentPage = 1; loadSagas(); }}
                                    disabled={currentPage === 1}
                                    class="pagination-button"
                                    title="First page"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                                    </svg>
                                </button>
                                
                                <!-- Previous page -->
                                <button
                                    on:click={() => { currentPage--; loadSagas(); }}
                                    disabled={currentPage === 1}
                                    class="pagination-button"
                                    title="Previous page"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
                                    </svg>
                                </button>
                                
                                <!-- Page numbers -->
                                <div class="pagination-text">
                                    <span class="font-medium">{currentPage}</span>
                                    <span class="text-fg-muted dark:text-dark-fg-muted mx-1">/</span>
                                    <span class="font-medium">{totalPages}</span>
                                </div>
                                
                                <!-- Next page -->
                                <button
                                    on:click={() => { currentPage++; loadSagas(); }}
                                    disabled={currentPage === totalPages}
                                    class="pagination-button"
                                    title="Next page"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                                    </svg>
                                </button>
                                
                                <!-- Last page -->
                                <button
                                    on:click={() => { currentPage = totalPages; loadSagas(); }}
                                    disabled={currentPage === totalPages}
                                    class="pagination-button"
                                    title="Last page"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                                    </svg>
                                </button>
                                </div>
                                {/if}
                            </div>
                            
                            <!-- Info text at the right -->
                            <div class="text-xs sm:text-sm text-fg-muted dark:text-dark-fg-muted">
                                Showing {(currentPage - 1) * itemsPerPage + 1} to {Math.min(currentPage * itemsPerPage, totalItems)} of {totalItems} sagas
                            </div>
                        </div>
                    </div>
                {/if}
            {/if}
        </div>
    </div>
</AdminLayout>

<!-- Saga Detail Modal -->
{#if showDetailModal && selectedSaga}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/70 z-50 flex items-center justify-center p-2 sm:p-4">
        <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[95vh] sm:max-h-[90vh] overflow-hidden">
            <div class="p-4 sm:p-6 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                <h2 class="text-lg sm:text-xl font-semibold text-gray-900 dark:text-gray-100">Saga Details</h2>
                <button
                    on:click={() => showDetailModal = false}
                    class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 text-2xl leading-none"
                >
                    ×
                </button>
            </div>
            
            <div class="p-4 sm:p-6 overflow-y-auto max-h-[calc(95vh-100px)] sm:max-h-[calc(90vh-120px)]">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
                    <!-- Basic Info -->
                    <div>
                        <h3 class="font-semibold mb-3 text-gray-900 dark:text-gray-100">Basic Information</h3>
                        <dl class="space-y-2 text-sm">
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Saga ID</dt>
                                <dd class="font-mono text-gray-900 dark:text-gray-100">{selectedSaga.saga_id}</dd>
                            </div>
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Saga Name</dt>
                                <dd class="font-medium text-gray-900 dark:text-gray-100">{selectedSaga.saga_name}</dd>
                            </div>
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Execution ID</dt>
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
                                <dt class="text-gray-500 dark:text-gray-400">State</dt>
                                <dd>
                                    <span class="px-2 py-1 text-xs rounded-full {getStateInfo(selectedSaga.state).color}">
                                        {getStateInfo(selectedSaga.state).label}
                                    </span>
                                </dd>
                            </div>
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Retry Count</dt>
                                <dd class="text-gray-900 dark:text-gray-100">{selectedSaga.retry_count}</dd>
                            </div>
                        </dl>
                    </div>
                    
                    <!-- Timing Info -->
                    <div>
                        <h3 class="font-semibold mb-3 text-gray-900 dark:text-gray-100">Timing Information</h3>
                        <dl class="space-y-2 text-sm">
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Created At</dt>
                                <dd class="text-gray-900 dark:text-gray-100">{formatDate(selectedSaga.created_at)}</dd>
                            </div>
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Updated At</dt>
                                <dd class="text-gray-900 dark:text-gray-100">{formatDate(selectedSaga.updated_at)}</dd>
                            </div>
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Completed At</dt>
                                <dd class="text-gray-900 dark:text-gray-100">{formatDate(selectedSaga.completed_at)}</dd>
                            </div>
                            <div>
                                <dt class="text-gray-500 dark:text-gray-400">Total Duration</dt>
                                <dd class="text-gray-900 dark:text-gray-100">{formatDuration(selectedSaga.created_at, selectedSaga.completed_at || selectedSaga.updated_at)}</dd>
                            </div>
                        </dl>
                    </div>
                </div>
                
                <!-- Steps Information -->
                <div class="mt-6">
                    <h3 class="font-semibold mb-3 text-gray-900 dark:text-gray-100">Execution Steps</h3>
                    
                    {#if selectedSaga.saga_name === 'execution_saga'}
                        <div class="mb-4 sm:mb-6 p-3 sm:p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg overflow-x-auto">
                            <div class="flex items-start justify-between gap-0 min-w-[600px] pb-2">
                                {#each executionSagaSteps as step, index}
                                    {@const isCompleted = selectedSaga.completed_steps.includes(step.name)}
                                    {@const isCompensated = selectedSaga.compensated_steps.includes(step.compensation) && step.compensation}
                                    {@const isCurrent = selectedSaga.current_step === step.name}
                                    {@const isFailed = selectedSaga.state === 'failed' && selectedSaga.current_step === step.name}
                                    
                                    <div class="flex flex-col items-center flex-1 relative">
                                        <div class="flex items-center w-full relative h-12">
                                            <div class="flex-1 flex items-center justify-end">
                                                {#if index > 0}
                                                    <div class="h-0.5 w-full
                                                        {selectedSaga.completed_steps.includes(executionSagaSteps[index - 1].name) && (isCompleted || isCompensated) ? 'bg-green-400 dark:bg-green-600' : 'bg-gray-300 dark:bg-gray-600'}">
                                                    </div>
                                                {/if}
                                            </div>
                                            <div class="relative z-10 mx-1">
                                                <div class="w-10 h-10 sm:w-12 sm:h-12 rounded-full flex items-center justify-center text-sm sm:text-lg font-semibold border-2
                                                    {isCompleted ? 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400 border-green-300 dark:border-green-600' : 
                                                     isCompensated ? 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400 border-yellow-300 dark:border-yellow-600' :
                                                     isCurrent ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 border-blue-300 dark:border-blue-600 animate-pulse' :
                                                     isFailed ? 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400 border-red-300 dark:border-red-600' :
                                                     'bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500 border-gray-300 dark:border-gray-600'}">
                                                    {#if isCompleted}
                                                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M5 13l4 4L19 7" />
                                                        </svg>
                                                    {:else if isCompensated}
                                                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                                                        </svg>
                                                    {:else if isCurrent}
                                                        <div class="w-2 h-2 bg-current rounded-full"></div>
                                                    {:else if isFailed}
                                                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 18L18 6M6 6l12 12" />
                                                        </svg>
                                                    {:else}
                                                        <span class="text-sm font-bold">{index + 1}</span>
                                                    {/if}
                                                </div>
                                            </div>
                                            <div class="flex-1 flex items-center justify-start">
                                                {#if index < executionSagaSteps.length - 1}
                                                    <div class="h-0.5 w-full
                                                        {isCompleted && selectedSaga.completed_steps.includes(executionSagaSteps[index + 1].name) ? 'bg-green-400 dark:bg-green-600' : 'bg-gray-300 dark:bg-gray-600'}">
                                                    </div>
                                                {/if}
                                            </div>
                                        </div>
                                        <div class="mt-2 sm:mt-3 text-[10px] sm:text-xs font-medium text-center px-1 min-w-[70px] sm:min-w-[80px]">
                                            {step.label}
                                            {#if step.compensation && isCompensated}
                                                <div class="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                                                    (compensated)
                                                </div>
                                            {/if}
                                        </div>
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
                    
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
                                <p class="text-sm text-gray-500 dark:text-gray-400">No completed steps</p>
                            {/if}
                        </div>
                        
                        <div>
                            <h4 class="text-sm font-medium mb-2 text-yellow-600">Compensated Steps ({selectedSaga.compensated_steps.length})</h4>
                            {#if selectedSaga.compensated_steps.length > 0}
                                <ul class="space-y-1">
                                    {#each selectedSaga.compensated_steps as step}
                                        <li class="flex items-center gap-2 text-sm">
                                            <svg class="w-4 h-4 text-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                                            </svg>
                                            <span>{step}</span>
                                        </li>
                                    {/each}
                                </ul>
                            {:else}
                                <p class="text-sm text-gray-500 dark:text-gray-400">No compensated steps</p>
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
                        <h3 class="font-semibold mb-3 text-gray-900 dark:text-gray-100">Context Data</h3>
                        <div class="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                            <pre class="text-sm overflow-x-auto text-gray-800 dark:text-gray-200">{JSON.stringify(selectedSaga.context_data, null, 2)}</pre>
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