<script>
    import { onMount, onDestroy } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let loading = true;
    let selectedTab = 'lag';
    let refreshInterval = null;
    let autoRefresh = true;
    let refreshRate = 30; // seconds
    
    // Data stores
    let lagMetrics = [];
    let throughputMetrics = [];
    let topicMetrics = [];
    let consumerGroups = [];
    let clusterMetrics = null;
    let selectedLagTrend = null;
    
    // Filters
    let lagFilters = { consumerGroup: '', topic: '' };
    let throughputFilters = { topic: '', direction: '' };
    let topicFilter = '';
    let groupFilter = '';
    
    // Modal states
    let showLagTrendModal = false;
    let lagTrendData = null;
    let lagTrendLoading = false;
    
    const tabs = [
        { id: 'lag', label: 'Consumer Lag', icon: '📊' },
        { id: 'throughput', label: 'Throughput', icon: '📈' },
        { id: 'topics', label: 'Topics', icon: '📁' },
        { id: 'groups', label: 'Consumer Groups', icon: '👥' },
        { id: 'cluster', label: 'Cluster Status', icon: '🖥️' }
    ];
    
    async function loadLagMetrics() {
        try {
            const params = new URLSearchParams();
            if (lagFilters.consumerGroup) params.append('consumer_group', lagFilters.consumerGroup);
            if (lagFilters.topic) params.append('topic', lagFilters.topic);
            
            const response = await api.get(`/api/v1/kafka/metrics/lag?${params}`);
            lagMetrics = response.data;
        } catch (error) {
            console.error('Failed to load lag metrics:', error);
            addNotification('Failed to load lag metrics', 'error');
        }
    }
    
    async function loadThroughputMetrics() {
        try {
            const params = new URLSearchParams();
            if (throughputFilters.topic) params.append('topic', throughputFilters.topic);
            if (throughputFilters.direction) params.append('direction', throughputFilters.direction);
            
            const response = await api.get(`/api/v1/kafka/metrics/throughput?${params}`);
            throughputMetrics = response.data;
        } catch (error) {
            console.error('Failed to load throughput metrics:', error);
            addNotification('Failed to load throughput metrics', 'error');
        }
    }
    
    async function loadTopicMetrics() {
        try {
            const params = new URLSearchParams();
            if (topicFilter) params.append('topic', topicFilter);
            
            const response = await api.get(`/api/v1/kafka/metrics/topics?${params}`);
            topicMetrics = response.data;
        } catch (error) {
            console.error('Failed to load topic metrics:', error);
            addNotification('Failed to load topic metrics', 'error');
        }
    }
    
    async function loadConsumerGroups() {
        try {
            const params = new URLSearchParams();
            if (groupFilter) params.append('group_id', groupFilter);
            
            const response = await api.get(`/api/v1/kafka/metrics/consumer-groups?${params}`);
            consumerGroups = response.data;
        } catch (error) {
            console.error('Failed to load consumer groups:', error);
            addNotification('Failed to load consumer groups', 'error');
        }
    }
    
    async function loadClusterMetrics() {
        try {
            const response = await api.get('/api/v1/kafka/metrics/cluster');
            clusterMetrics = response.data;
        } catch (error) {
            console.error('Failed to load cluster metrics:', error);
            addNotification('Failed to load cluster metrics', 'error');
        }
    }
    
    async function loadLagTrend(consumerGroup, topic, partition) {
        try {
            lagTrendLoading = true;
            showLagTrendModal = true;
            
            const response = await api.get(
                `/api/v1/kafka/metrics/lag/trend/${consumerGroup}/${topic}/${partition}?window_minutes=60`
            );
            lagTrendData = response.data;
        } catch (error) {
            console.error('Failed to load lag trend:', error);
            addNotification('Failed to load lag trend', 'error');
            showLagTrendModal = false;
        } finally {
            lagTrendLoading = false;
        }
    }
    
    async function loadMetrics() {
        loading = true;
        try {
            switch (selectedTab) {
                case 'lag':
                    await loadLagMetrics();
                    break;
                case 'throughput':
                    await loadThroughputMetrics();
                    break;
                case 'topics':
                    await loadTopicMetrics();
                    break;
                case 'groups':
                    await loadConsumerGroups();
                    break;
                case 'cluster':
                    await loadClusterMetrics();
                    break;
            }
        } finally {
            loading = false;
        }
    }
    
    function setupAutoRefresh() {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
        
        if (autoRefresh) {
            refreshInterval = setInterval(() => {
                loadMetrics();
            }, refreshRate * 1000);
        }
    }
    
    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    function formatNumber(num) {
        return new Intl.NumberFormat().format(num);
    }
    
    function getStatusColor(status) {
        switch (status) {
            case 'healthy':
                return 'text-green-600 bg-green-100';
            case 'degraded':
                return 'text-yellow-600 bg-yellow-100';
            case 'unhealthy':
                return 'text-red-600 bg-red-100';
            default:
                return 'text-gray-600 bg-gray-100';
        }
    }
    
    function getTrendIcon(trend) {
        switch (trend) {
            case 'increasing':
                return '📈';
            case 'decreasing':
                return '📉';
            case 'stable':
                return '➡️';
            default:
                return '❓';
        }
    }
    
    onMount(() => {
        loadMetrics();
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
    
    $: if (selectedTab) {
        loadMetrics();
    }
</script>

<AdminLayout path="/admin/kafka">
    <div class="px-6 pb-6">
        <div class="mb-6">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">
                Kafka Metrics Dashboard
            </h1>
            <p class="text-fg-muted dark:text-dark-fg-muted">
                Monitor Kafka cluster health, consumer lag, throughput, and more
            </p>
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
                    <label class="text-sm">Refresh every:</label>
                    <select
                        bind:value={refreshRate}
                        class="px-3 py-1 rounded border border-border-default dark:border-dark-border-default bg-bg-default dark:bg-dark-bg-default"
                    >
                        <option value={10}>10 seconds</option>
                        <option value={30}>30 seconds</option>
                        <option value={60}>1 minute</option>
                        <option value={300}>5 minutes</option>
                    </select>
                </div>
            {/if}
            <button
                on:click={loadMetrics}
                class="ml-auto px-4 py-2 bg-primary text-white rounded hover:bg-primary-dark transition-colors"
                disabled={loading}
            >
                {loading ? 'Refreshing...' : 'Refresh Now'}
            </button>
        </div>
        
        <!-- Tabs -->
        <div class="mb-6 border-b border-border-default dark:border-dark-border-default">
            <div class="flex space-x-8">
                {#each tabs as tab}
                    <button
                        on:click={() => selectedTab = tab.id}
                        class="pb-4 px-1 border-b-2 transition-colors {selectedTab === tab.id 
                            ? 'border-primary text-primary' 
                            : 'border-transparent text-fg-muted hover:text-fg-default'}"
                    >
                        <span class="flex items-center gap-2">
                            <span>{tab.icon}</span>
                            <span>{tab.label}</span>
                        </span>
                    </button>
                {/each}
            </div>
        </div>
        
        <!-- Tab Content -->
        <div class="bg-bg-default dark:bg-dark-bg-default rounded-lg shadow">
            {#if loading}
                <div class="p-8 text-center">
                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
                    <p class="text-fg-muted">Loading metrics...</p>
                </div>
            {:else if selectedTab === 'lag'}
                <!-- Consumer Lag Tab -->
                <div class="px-6 pb-6">
                    <div class="mb-4 grid grid-cols-2 gap-4">
                        <input
                            type="text"
                            placeholder="Filter by consumer group..."
                            bind:value={lagFilters.consumerGroup}
                            on:input={loadLagMetrics}
                            class="px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                        />
                        <input
                            type="text"
                            placeholder="Filter by topic..."
                            bind:value={lagFilters.topic}
                            on:input={loadLagMetrics}
                            class="px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                        />
                    </div>
                    
                    <div class="overflow-x-auto">
                        <table class="w-full">
                            <thead>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <th class="px-4 py-3 text-left">Consumer Group</th>
                                    <th class="px-4 py-3 text-left">Topic</th>
                                    <th class="px-4 py-3 text-left">Partition</th>
                                    <th class="px-4 py-3 text-right">Current Lag</th>
                                    <th class="px-4 py-3 text-center">Trend</th>
                                    <th class="px-4 py-3 text-right">Rate/min</th>
                                    <th class="px-4 py-3 text-center">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {#each lagMetrics as metric}
                                    <tr class="border-b border-border-default dark:border-dark-border-default hover:bg-bg-alt dark:hover:bg-dark-bg-alt">
                                        <td class="px-4 py-3">{metric.consumer_group}</td>
                                        <td class="px-4 py-3">{metric.topic}</td>
                                        <td class="px-4 py-3">{metric.partition}</td>
                                        <td class="px-4 py-3 text-right font-mono">
                                            {formatNumber(metric.current_lag)}
                                        </td>
                                        <td class="px-4 py-3 text-center">
                                            <span title={metric.trend}>
                                                {getTrendIcon(metric.trend)}
                                            </span>
                                        </td>
                                        <td class="px-4 py-3 text-right font-mono">
                                            {metric.rate_per_minute.toFixed(2)}
                                        </td>
                                        <td class="px-4 py-3 text-center">
                                            <button
                                                on:click={() => loadLagTrend(metric.consumer_group, metric.topic, metric.partition)}
                                                class="text-primary hover:text-primary-dark"
                                            >
                                                View Trend
                                            </button>
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                        
                        {#if lagMetrics.length === 0}
                            <p class="text-center py-8 text-fg-muted">No lag metrics found</p>
                        {/if}
                    </div>
                </div>
                
            {:else if selectedTab === 'throughput'}
                <!-- Throughput Tab -->
                <div class="px-6 pb-6">
                    <div class="mb-4 grid grid-cols-2 gap-4">
                        <input
                            type="text"
                            placeholder="Filter by topic..."
                            bind:value={throughputFilters.topic}
                            on:input={loadThroughputMetrics}
                            class="px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                        />
                        <select
                            bind:value={throughputFilters.direction}
                            on:change={loadThroughputMetrics}
                            class="px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                        >
                            <option value="">All directions</option>
                            <option value="in">Consumed (in)</option>
                            <option value="out">Produced (out)</option>
                        </select>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {#each throughputMetrics as metric}
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex justify-between items-start mb-2">
                                    <h3 class="font-semibold">{metric.topic}</h3>
                                    <span class="px-2 py-1 text-xs rounded {metric.direction === 'in' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}">
                                        {metric.direction === 'in' ? 'Consumed' : 'Produced'}
                                    </span>
                                </div>
                                <div class="space-y-2">
                                    <div class="flex justify-between">
                                        <span class="text-fg-muted">Messages/sec:</span>
                                        <span class="font-mono">{metric.messages_per_second.toFixed(2)}</span>
                                    </div>
                                    <div class="flex justify-between">
                                        <span class="text-fg-muted">Throughput:</span>
                                        <span class="font-mono">{formatBytes(metric.bytes_per_second)}/s</span>
                                    </div>
                                    <div class="text-xs text-fg-muted">
                                        Last updated: {new Date(metric.timestamp).toLocaleTimeString()}
                                    </div>
                                </div>
                            </div>
                        {/each}
                    </div>
                    
                    {#if throughputMetrics.length === 0}
                        <p class="text-center py-8 text-fg-muted">No throughput metrics found</p>
                    {/if}
                </div>
                
            {:else if selectedTab === 'topics'}
                <!-- Topics Tab -->
                <div class="px-6 pb-6">
                    <div class="mb-4">
                        <input
                            type="text"
                            placeholder="Filter by topic name..."
                            bind:value={topicFilter}
                            on:input={loadTopicMetrics}
                            class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                        />
                    </div>
                    
                    <div class="overflow-x-auto">
                        <table class="w-full">
                            <thead>
                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                    <th class="px-4 py-3 text-left">Topic</th>
                                    <th class="px-4 py-3 text-center">Partitions</th>
                                    <th class="px-4 py-3 text-center">Replication</th>
                                    <th class="px-4 py-3 text-right">Messages Produced</th>
                                    <th class="px-4 py-3 text-right">Messages Consumed</th>
                                    <th class="px-4 py-3 text-right">Errors</th>
                                </tr>
                            </thead>
                            <tbody>
                                {#each topicMetrics as metric}
                                    <tr class="border-b border-border-default dark:border-dark-border-default hover:bg-bg-alt dark:hover:bg-dark-bg-alt">
                                        <td class="px-4 py-3 font-medium">{metric.topic}</td>
                                        <td class="px-4 py-3 text-center">{metric.partition_count}</td>
                                        <td class="px-4 py-3 text-center">{metric.replication_factor}</td>
                                        <td class="px-4 py-3 text-right font-mono">
                                            {formatNumber(metric.total_messages_produced)}
                                        </td>
                                        <td class="px-4 py-3 text-right font-mono">
                                            {formatNumber(metric.total_messages_consumed)}
                                        </td>
                                        <td class="px-4 py-3 text-right">
                                            <span class="{metric.total_errors > 0 ? 'text-red-600' : ''}">
                                                {formatNumber(metric.total_errors)}
                                            </span>
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                        
                        {#if topicMetrics.length === 0}
                            <p class="text-center py-8 text-fg-muted">No topics found</p>
                        {/if}
                    </div>
                </div>
                
            {:else if selectedTab === 'groups'}
                <!-- Consumer Groups Tab -->
                <div class="px-6 pb-6">
                    <div class="mb-4">
                        <input
                            type="text"
                            placeholder="Filter by group ID..."
                            bind:value={groupFilter}
                            on:input={loadConsumerGroups}
                            class="w-full px-4 py-2 border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default"
                        />
                    </div>
                    
                    <div class="space-y-4">
                        {#each consumerGroups as group}
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex justify-between items-start mb-3">
                                    <h3 class="font-semibold text-lg">{group.group_id}</h3>
                                    <div class="flex gap-2">
                                        <span class="px-2 py-1 text-xs rounded bg-blue-100 text-blue-700">
                                            Lag: {formatNumber(group.total_lag)}
                                        </span>
                                        {#if group.total_errors > 0}
                                            <span class="px-2 py-1 text-xs rounded bg-red-100 text-red-700">
                                                Errors: {formatNumber(group.total_errors)}
                                            </span>
                                        {/if}
                                    </div>
                                </div>
                                
                                <div class="grid grid-cols-2 gap-4 mb-3">
                                    <div>
                                        <span class="text-sm text-fg-muted">Topics:</span>
                                        <div class="flex flex-wrap gap-1 mt-1">
                                            {#each group.topics as topic}
                                                <span class="px-2 py-1 text-xs bg-bg-alt dark:bg-dark-bg-alt rounded">
                                                    {topic}
                                                </span>
                                            {/each}
                                        </div>
                                    </div>
                                    <div>
                                        <span class="text-sm text-fg-muted">Messages Consumed:</span>
                                        <p class="font-mono">{formatNumber(group.total_messages_consumed)}</p>
                                    </div>
                                </div>
                                
                                {#if group.partitions.length > 0}
                                    <details class="mt-3">
                                        <summary class="cursor-pointer text-sm text-primary hover:text-primary-dark">
                                            View partition details ({group.partitions.length} partitions)
                                        </summary>
                                        <div class="mt-2 text-sm space-y-1">
                                            {#each group.partitions as partition}
                                                <div class="flex justify-between py-1 px-2 hover:bg-bg-alt dark:hover:bg-dark-bg-alt rounded">
                                                    <span>{partition.topic}:{partition.partition}</span>
                                                    <span class="font-mono">Lag: {formatNumber(partition.lag)}</span>
                                                </div>
                                            {/each}
                                        </div>
                                    </details>
                                {/if}
                            </div>
                        {/each}
                    </div>
                    
                    {#if consumerGroups.length === 0}
                        <p class="text-center py-8 text-fg-muted">No consumer groups found</p>
                    {/if}
                </div>
                
            {:else if selectedTab === 'cluster'}
                <!-- Cluster Status Tab -->
                <div class="px-6 pb-6">
                    {#if clusterMetrics}
                        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            <!-- Cluster Health -->
                            <div class="col-span-full">
                                <div class="p-6 border border-border-default dark:border-dark-border-default rounded-lg">
                                    <h3 class="text-lg font-semibold mb-4">Cluster Health</h3>
                                    <div class="flex items-center gap-4">
                                        <span class="px-4 py-2 rounded-full text-sm font-medium {getStatusColor(clusterMetrics.cluster_status)}">
                                            {clusterMetrics.cluster_status.toUpperCase()}
                                        </span>
                                        <div class="text-sm text-fg-muted">
                                            Last updated: {new Date().toLocaleTimeString()}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Brokers -->
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                                        <span class="text-blue-600">🖥️</span>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold">Brokers</h4>
                                        <p class="text-2xl font-bold">{clusterMetrics.broker_count}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Topics -->
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                                        <span class="text-green-600">📁</span>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold">Topics</h4>
                                        <p class="text-2xl font-bold">{clusterMetrics.topic_count}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Consumer Groups -->
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                                        <span class="text-purple-600">👥</span>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold">Consumer Groups</h4>
                                        <p class="text-2xl font-bold">{clusterMetrics.consumer_group_count}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Messages Produced -->
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center">
                                        <span class="text-indigo-600">📤</span>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold">Messages Produced</h4>
                                        <p class="text-2xl font-bold">{formatNumber(clusterMetrics.total_messages_produced)}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Messages Consumed -->
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="w-10 h-10 bg-teal-100 rounded-lg flex items-center justify-center">
                                        <span class="text-teal-600">📥</span>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold">Messages Consumed</h4>
                                        <p class="text-2xl font-bold">{formatNumber(clusterMetrics.total_messages_consumed)}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Total Errors -->
                            <div class="p-4 border border-border-default dark:border-dark-border-default rounded-lg">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center">
                                        <span class="text-red-600">⚠️</span>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold">Total Errors</h4>
                                        <p class="text-2xl font-bold {clusterMetrics.total_errors > 0 ? 'text-red-600' : ''}">
                                            {formatNumber(clusterMetrics.total_errors)}
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    {/if}
                </div>
            {/if}
        </div>
    </div>
</AdminLayout>

<!-- Lag Trend Modal -->
{#if showLagTrendModal}
    <div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
        <div class="bg-bg-default dark:bg-dark-bg-default rounded-lg shadow-xl max-w-4xl w-full max-h-[80vh] overflow-hidden">
            <div class="p-6 border-b border-border-default dark:border-dark-border-default flex justify-between items-center">
                <h2 class="text-xl font-semibold">Lag Trend Analysis</h2>
                <button
                    on:click={() => showLagTrendModal = false}
                    class="text-fg-muted hover:text-fg-default"
                >
                    ✕
                </button>
            </div>
            
            <div class="p-6 overflow-y-auto max-h-[calc(80vh-120px)]">
                {#if lagTrendLoading}
                    <div class="text-center py-8">
                        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
                        <p class="text-fg-muted">Loading trend data...</p>
                    </div>
                {:else if lagTrendData}
                    <div class="space-y-4">
                        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                            <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                                <p class="text-sm text-fg-muted">Current Lag</p>
                                <p class="text-2xl font-bold">{formatNumber(lagTrendData.current_lag)}</p>
                            </div>
                            <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                                <p class="text-sm text-fg-muted">Trend</p>
                                <p class="text-2xl">
                                    {getTrendIcon(lagTrendData.trend)} {lagTrendData.trend}
                                </p>
                            </div>
                            <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                                <p class="text-sm text-fg-muted">Min Lag</p>
                                <p class="text-2xl font-bold">{formatNumber(lagTrendData.min_lag || 0)}</p>
                            </div>
                            <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                                <p class="text-sm text-fg-muted">Max Lag</p>
                                <p class="text-2xl font-bold">{formatNumber(lagTrendData.max_lag || 0)}</p>
                            </div>
                        </div>
                        
                        {#if lagTrendData.rate_per_minute}
                            <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg">
                                <p class="text-sm text-fg-muted">Rate of Change</p>
                                <p class="text-lg">
                                    <span class="{lagTrendData.rate_per_minute > 0 ? 'text-red-600' : 'text-green-600'}">
                                        {lagTrendData.rate_per_minute > 0 ? '+' : ''}{lagTrendData.rate_per_minute.toFixed(2)}
                                    </span>
                                    messages/minute
                                </p>
                            </div>
                        {/if}
                        
                        {#if lagTrendData.historical_data && lagTrendData.historical_data.length > 0}
                            <div>
                                <h3 class="font-semibold mb-2">Historical Data</h3>
                                <div class="overflow-x-auto">
                                    <table class="w-full text-sm">
                                        <thead>
                                            <tr class="border-b border-border-default dark:border-dark-border-default">
                                                <th class="px-4 py-2 text-left">Time</th>
                                                <th class="px-4 py-2 text-right">Lag</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {#each lagTrendData.historical_data as point}
                                                <tr class="border-b border-border-default dark:border-dark-border-default">
                                                    <td class="px-4 py-2">
                                                        {new Date(point.timestamp).toLocaleTimeString()}
                                                    </td>
                                                    <td class="px-4 py-2 text-right font-mono">
                                                        {formatNumber(point.lag)}
                                                    </td>
                                                </tr>
                                            {/each}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        {/if}
                    </div>
                {/if}
            </div>
        </div>
    </div>
{/if}

<style>
    details summary::-webkit-details-marker {
        display: none;
    }
</style>