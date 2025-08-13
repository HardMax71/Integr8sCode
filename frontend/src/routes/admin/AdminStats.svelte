<script>
    import { onMount, onDestroy } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let stats = null;
    let executionSummary = null;
    let errorAnalysis = null;
    let languageUsage = null;
    let loading = true;
    let refreshInterval = null;
    let selectedHours = 24;
    
    const hourOptions = [
        { value: 1, label: 'Last Hour' },
        { value: 6, label: 'Last 6 Hours' },
        { value: 24, label: 'Last 24 Hours' },
        { value: 72, label: 'Last 3 Days' },
        { value: 168, label: 'Last Week' }
    ];
    
    onMount(() => {
        loadAllStats();
        refreshInterval = setInterval(loadAllStats, 60000); // Refresh every minute
    });
    
    onDestroy(() => {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
    });
    
    async function loadAllStats() {
        loading = true;
        try {
            await Promise.all([
                loadEventStats(),
                loadExecutionSummary(),
                loadErrorAnalysis(),
                loadLanguageUsage()
            ]);
        } catch (error) {
            addNotification(`Failed to load statistics: ${error.message}`, 'error');
        } finally {
            loading = false;
        }
    }
    
    async function loadEventStats() {
        stats = await api.get(`/api/v1/admin/events/stats?hours=${selectedHours}`);
    }
    
    async function loadExecutionSummary() {
        // Get current user for demo - in real app, this would be aggregate stats
        try {
            const user = await api.get('/api/v1/auth/me');
            executionSummary = await api.get(`/api/v1/projections/execution-summary/${user.user_id}`);
        } catch (error) {
            console.error('Failed to load execution summary:', error);
        }
    }
    
    async function loadErrorAnalysis() {
        try {
            errorAnalysis = await api.get('/api/v1/projections/error-analysis?limit=10');
        } catch (error) {
            console.error('Failed to load error analysis:', error);
        }
    }
    
    async function loadLanguageUsage() {
        try {
            languageUsage = await api.get('/api/v1/projections/language-usage');
        } catch (error) {
            console.error('Failed to load language usage:', error);
        }
    }
    
    function getMaxEventCount() {
        if (!stats?.events_by_hour?.length) return 1;
        return Math.max(...stats.events_by_hour.map(h => h.count));
    }
    
    function getBarHeight(count) {
        const maxCount = getMaxEventCount();
        return `${(count / maxCount) * 100}%`;
    }
</script>

<AdminLayout path="/admin/stats">
    <div class="container mx-auto px-4 pb-8">
        <div class="flex justify-between items-center mb-6">
            <h1 class="text-3xl font-bold">System Statistics</h1>
            
            <select
                bind:value={selectedHours}
                on:change={loadAllStats}
                class="form-select-standard w-48"
            >
                {#each hourOptions || [] as option}
                    <option value={option.value}>{option.label}</option>
                {/each}
            </select>
        </div>
        
        {#if loading && !stats}
            <div class="flex justify-center items-center h-64">
                <svg class="animate-spin h-12 w-12 text-primary" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
            </div>
        {:else if stats}
            <!-- Key Metrics -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                <div class="card p-4">
                    <div class="flex justify-between items-start mb-2">
                        <div>
                            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Total Events</div>
                            <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{stats?.total_events?.toLocaleString() || '0'}</div>
                            <div class="text-xs text-fg-muted dark:text-dark-fg-muted mt-1">Last {selectedHours} hours</div>
                        </div>
                        <svg class="w-8 h-8 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                    </div>
                </div>
                
                <div class="card p-4">
                    <div class="flex justify-between items-start mb-2">
                        <div>
                            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Error Rate</div>
                            <div class="text-2xl font-bold text-red-600 dark:text-red-400">{stats.error_rate}%</div>
                            <div class="text-xs text-fg-muted dark:text-dark-fg-muted mt-1">Failed executions</div>
                        </div>
                        <svg class="w-8 h-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                </div>
                
                <div class="card p-4">
                    <div class="flex justify-between items-start mb-2">
                        <div>
                            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Avg Processing</div>
                            <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{stats.avg_processing_time}s</div>
                            <div class="text-xs text-fg-muted dark:text-dark-fg-muted mt-1">Execution time</div>
                        </div>
                        <svg class="w-8 h-8 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                    </div>
                </div>
                
                <div class="card p-4">
                    <div class="flex justify-between items-start mb-2">
                        <div>
                            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Active Users</div>
                            <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{stats.top_users.length}</div>
                            <div class="text-xs text-fg-muted dark:text-dark-fg-muted mt-1">Unique users</div>
                        </div>
                        <svg class="w-8 h-8 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                        </svg>
                    </div>
                </div>
            </div>
            
            <!-- Charts -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                <!-- Events Over Time -->
                <div class="card">
                    <div class="p-6">
                        <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default">Events Over Time</h3>
                        {#if stats?.events_by_hour?.length > 0}
                            <div class="h-64 flex items-end gap-1">
                                {#each stats?.events_by_hour || [] as hourData}
                                    <div class="flex-1 flex flex-col items-center">
                                        <div 
                                            class="w-full bg-primary transition-all duration-300"
                                            style={`height: ${getBarHeight(hourData.count)}`}
                                            title={`${hourData.count} events`}
                                        />
                                        <span class="text-xs mt-1 rotate-45 origin-left">
                                            {new Date(hourData.hour).getHours()}h
                                        </span>
                                    </div>
                                {/each}
                            </div>
                        {:else}
                            <div class="h-64 flex items-center justify-center">
                                <p class="text-fg-muted dark:text-dark-fg-muted text-sm">No data available</p>
                            </div>
                        {/if}
                    </div>
                </div>
                
                <!-- Events by Type -->
                <div class="card">
                    <div class="p-6">
                        <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default">Events by Type</h3>
                        {#if stats?.events_by_type && Object.keys(stats.events_by_type).length > 0}
                            <div class="space-y-2">
                                {#each Object.entries(stats?.events_by_type || {}).slice(0, 10) as [type, count]}
                                    <div class="flex items-center gap-2">
                                        <span class="text-sm w-40 truncate" title={type}>{type}</span>
                                        <div class="flex-1 bg-neutral-200 dark:bg-neutral-700 rounded-full h-4">
                                            <div 
                                                class="bg-primary h-4 rounded-full"
                                                style={`width: ${(count / stats.total_events) * 100}%`}
                                            />
                                        </div>
                                        <span class="text-sm w-16 text-right">{count}</span>
                                    </div>
                                {/each}
                            </div>
                        {:else}
                            <div class="h-64 flex items-center justify-center">
                                <p class="text-fg-muted dark:text-dark-fg-muted text-sm">No data available</p>
                            </div>
                        {/if}
                    </div>
                </div>
            </div>
            
            <!-- Top Users and Errors -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- Top Users -->
                <div class="card">
                    <div class="p-6">
                        <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Top Users</h3>
                        <div class="overflow-x-auto">
                            <table class="w-full">
                                <thead class="bg-neutral-50 dark:bg-neutral-900">
                                    <tr>
                                        <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">User ID</th>
                                        <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Events</th>
                                        <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Activity</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {#if stats?.top_users?.length > 0}
                                        {#each stats?.top_users || [] as user}
                                            <tr class="border-b border-border-default dark:border-dark-border-default">
                                                <td class="px-4 py-2 font-mono text-sm text-fg-default dark:text-dark-fg-default">{user.user_id || 'Anonymous'}</td>
                                                <td class="px-4 py-2 text-sm text-fg-default dark:text-dark-fg-default">{user?.event_count?.toLocaleString() || '0'}</td>
                                                <td class="px-4 py-2">
                                                    <div class="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                                                        <div 
                                                            class="bg-primary h-2 rounded-full"
                                                            style={`width: ${(user.event_count / stats.top_users[0].event_count) * 100}%`}
                                                        />
                                                    </div>
                                                </td>
                                            </tr>
                                        {/each}
                                    {:else}
                                        <tr>
                                            <td colspan="3" class="px-4 py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                                                No data available
                                            </td>
                                        </tr>
                                    {/if}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
                
                <!-- Error Analysis -->
                <div class="card">
                    <div class="p-6">
                        <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Top Errors</h3>
                        {#if errorAnalysis?.error_types && Object.keys(errorAnalysis.error_types).length > 0}
                            <div class="space-y-3">
                                {#each Object.entries(errorAnalysis?.error_types || {}).slice(0, 5) as [errorType, data]}
                                    <div class="border-l-4 border-red-600 dark:border-red-400 pl-3">
                                        <p class="font-semibold text-red-600 dark:text-red-400">{errorType}</p>
                                        <p class="text-sm text-fg-muted dark:text-dark-fg-muted">
                                            {data.total_occurrences} occurrences in {data.languages.join(', ')}
                                        </p>
                                    </div>
                                {/each}
                            </div>
                        {:else}
                            <div class="h-40 flex items-center justify-center">
                                <p class="text-fg-muted dark:text-dark-fg-muted text-sm">No errors recorded</p>
                            </div>
                        {/if}
                    </div>
                </div>
            </div>
            
            <!-- Language Usage -->
            <div class="card mt-6">
                <div class="p-6">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Language Usage</h3>
                    {#if languageUsage?.languages && Object.keys(languageUsage.languages).length > 0}
                        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {#each Object.entries(languageUsage?.languages || {}).slice(0, 8) as [lang, data]}
                                <div class="text-center p-4 bg-neutral-100 dark:bg-neutral-800 rounded-lg">
                                    <p class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{data?.total_usage?.toLocaleString() || '0'}</p>
                                    <p class="text-sm font-semibold text-fg-default dark:text-dark-fg-default">{lang}</p>
                                    <p class="text-xs text-fg-muted dark:text-dark-fg-muted">{data.unique_users} users</p>
                                </div>
                            {/each}
                        </div>
                    {:else}
                        <div class="h-40 flex items-center justify-center">
                            <p class="text-fg-muted dark:text-dark-fg-muted text-sm">No language usage data available</p>
                        </div>
                    {/if}
                </div>
            </div>
        {/if}
    </div>
</AdminLayout>