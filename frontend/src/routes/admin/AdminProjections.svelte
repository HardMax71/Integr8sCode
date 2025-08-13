<script>
    import { onMount, onDestroy, afterUpdate } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let projections = [];
    let loading = false;
    let selectedProjection = null;
    let refreshInterval = null;
    let isManualRefresh = false;
    let currentChart = null;
    let chartLoaded = false;
    
    const statusColors = {
        'active': 'text-green-600 dark:text-green-400',
        'paused': 'text-yellow-600 dark:text-yellow-400',
        'error': 'text-red-600 dark:text-red-400',
        'rebuilding': 'text-blue-600 dark:text-blue-400'
    };
    
    onMount(() => {
        loadProjections();
        // Auto-refresh every 10 seconds
        refreshInterval = setInterval(loadProjections, 10000);
        
        // Load Chart.js from CDN
        if (!window.Chart) {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js';
            script.onload = () => {
                chartLoaded = true;
            };
            document.head.appendChild(script);
        } else {
            chartLoaded = true;
        }
    });
    
    onDestroy(() => {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
        if (currentChart) {
            currentChart.destroy();
        }
    });
    
    async function loadProjections() {
        // Only show loading state for manual refresh
        if (isManualRefresh) {
            loading = true;
        }
        try {
            const response = await api.get('/api/v1/projections/');
            projections = Array.isArray(response) ? response : [];
            // Show success notification only on manual refresh
            if (isManualRefresh) {
                addNotification('Projections refreshed successfully', 'success');
            }
        } catch (error) {
            console.error('Failed to load projections:', error);
            addNotification(`Failed to load projections: ${error.message}`, 'error');
            projections = [];
        } finally {
            loading = false;
            isManualRefresh = false;
        }
    }
    
    async function manageProjection(action, projectionName) {
        loading = true;
        try {
            const response = await api.post('/api/v1/projections/actions', {
                action,
                projection_names: [projectionName]
            });
            
            const result = response.results[projectionName];
            if (result.includes('error')) {
                addNotification(`Failed to ${action} ${projectionName}: ${result}`, 'error');
            } else {
                addNotification(`${projectionName} ${result}`, 'success');
            }
            
            await loadProjections();
        } catch (error) {
            addNotification(`Failed to ${action} projection: ${error.message}`, 'error');
        } finally {
            loading = false;
        }
    }
    
    async function queryProjection(projectionName) {
        try {
            const response = await api.post('/api/v1/projections/query', {
                projection_name: projectionName,
                filters: {},
                limit: 100,
                sort: { '_id.timestamp': -1 }
            });
            
            selectedProjection = {
                name: projectionName,
                data: response.data,
                total: response.total
            };
            
            // Wait for DOM update then create chart
            setTimeout(() => {
                if (chartLoaded && window.Chart) {
                    createChart(projectionName, response.data);
                }
            }, 100);
        } catch (error) {
            addNotification(`Failed to query projection: ${error.message}`, 'error');
        }
    }
    
    function createChart(projectionName, data) {
        if (currentChart) {
            currentChart.destroy();
            currentChart = null;
        }
        
        if (!data || data.length === 0) return;
        
        const canvas = document.getElementById(`chart-${projectionName}`);
        if (!canvas) {
            console.error(`Canvas not found: chart-${projectionName}`);
            return;
        }
        
        const ctx = canvas.getContext('2d');
        const chartConfig = getChartConfig(projectionName, data);
        
        if (chartConfig && window.Chart) {
            currentChart = new window.Chart(ctx, chartConfig);
        }
    }
    
    function getChartConfig(projectionName, data) {
        switch(projectionName) {
            case 'user_activity':
                return getUserActivityChartConfig(data);
            case 'language_usage':
                return getLanguageUsageChartConfig(data);
            case 'error_analysis':
                return getErrorAnalysisChartConfig(data);
            case 'execution_status':
                return getExecutionStatusChartConfig(data);
            case 'execution_summary':
                return getExecutionSummaryChartConfig(data);
            case 'performance_metrics':
                return getPerformanceMetricsChartConfig(data);
            case 'settings_trends':
                return getSettingsTrendsChartConfig(data);
            default:
                return getGenericChartConfig(data);
        }
    }
    
    function getUserActivityChartConfig(data) {
        // Group by hour and aggregate execution counts
        const timeData = {};
        data.forEach(item => {
            const hour = item._id.hour;
            if (!hour) return;
            
            // Parse hour format "2025-08-09-14" to create proper date
            const [year, month, day, hourNum] = hour.split('-');
            const dateStr = `${year}-${month}-${day}T${hourNum.padStart(2, '0')}:00:00`;
            
            if (!timeData[dateStr]) {
                timeData[dateStr] = 0;
            }
            timeData[dateStr] += item.execution_count || 1;
        });
        
        const labels = Object.keys(timeData).sort();
        const values = labels.map(label => timeData[label]);
        
        return {
            type: 'line',
            data: {
                labels: labels.map(l => new Date(l).toLocaleString()),
                datasets: [{
                    label: 'Executions',
                    data: values,
                    borderColor: 'rgb(59, 130, 246)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'User Activity Over Time'
                    },
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Number of Executions'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Time'
                        }
                    }
                }
            }
        };
    }
    
    function getLanguageUsageChartConfig(data) {
        const languages = {};
        data.forEach(item => {
            const lang = item._id.language || 'Unknown';
            languages[lang] = (languages[lang] || 0) + (item.usage_count || 1);
        });
        
        return {
            type: 'doughnut',
            data: {
                labels: Object.keys(languages),
                datasets: [{
                    data: Object.values(languages),
                    backgroundColor: [
                        'rgb(59, 130, 246)',
                        'rgb(34, 197, 94)',
                        'rgb(251, 146, 60)',
                        'rgb(168, 85, 247)',
                        'rgb(236, 72, 153)',
                        'rgb(245, 158, 11)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Language Usage Distribution'
                    },
                    legend: {
                        position: 'right'
                    }
                }
            }
        };
    }
    
    function getErrorAnalysisChartConfig(data) {
        const errorTypes = {};
        data.forEach(item => {
            const error = item._id.error_type || 'Unknown';
            errorTypes[error] = (errorTypes[error] || 0) + (item.error_count || 1);
        });
        
        const sorted = Object.entries(errorTypes)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10);
        
        return {
            type: 'bar',
            data: {
                labels: sorted.map(([type]) => type),
                datasets: [{
                    label: 'Error Count',
                    data: sorted.map(([, count]) => count),
                    backgroundColor: 'rgba(239, 68, 68, 0.5)',
                    borderColor: 'rgb(239, 68, 68)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Top Error Types'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Occurrences'
                        }
                    }
                }
            }
        };
    }
    
    function getExecutionStatusChartConfig(data) {
        const statuses = {};
        data.forEach(item => {
            const status = item._id.status || 'Unknown';
            statuses[status] = (statuses[status] || 0) + (item.count || 1);
        });
        
        return {
            type: 'pie',
            data: {
                labels: Object.keys(statuses),
                datasets: [{
                    data: Object.values(statuses),
                    backgroundColor: [
                        'rgb(34, 197, 94)',
                        'rgb(239, 68, 68)',
                        'rgb(251, 146, 60)',
                        'rgb(168, 85, 247)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Execution Status Distribution'
                    }
                }
            }
        };
    }
    
    function getExecutionSummaryChartConfig(data) {
        // Group by date and aggregate status counts across all users
        const dateStatusData = {};
        
        console.log('Execution Summary Data:', data);
        
        data.forEach(item => {
            // Extract timestamp from _id.timestamp field
            const timestamp = item._id?.timestamp;
            if (!timestamp) return;
            
            // Convert timestamp to date string
            const date = new Date(timestamp * 1000).toISOString().split('T')[0];
            
            if (!dateStatusData[date]) {
                dateStatusData[date] = {
                    completed: 0,
                    failed: 0,
                    timeout: 0,
                    cancelled: 0,
                    total: 0
                };
            }
            
            // Aggregate counts from the projection data
            dateStatusData[date].completed += item.completed || 0;
            dateStatusData[date].failed += item.failed || 0;
            dateStatusData[date].timeout += item.timeout || 0;
            dateStatusData[date].cancelled += item.cancelled || 0;
            dateStatusData[date].total += item.total || 0;
        });
        
        const dates = Object.keys(dateStatusData).sort();
        
        return {
            type: 'bar',
            data: {
                labels: dates,
                datasets: [
                    {
                        label: 'Completed',
                        data: dates.map(date => dateStatusData[date].completed),
                        backgroundColor: 'rgba(34, 197, 94, 0.8)',
                        stack: 'Stack 0'
                    },
                    {
                        label: 'Failed',
                        data: dates.map(date => dateStatusData[date].failed),
                        backgroundColor: 'rgba(239, 68, 68, 0.8)',
                        stack: 'Stack 0'
                    },
                    {
                        label: 'Timeout',
                        data: dates.map(date => dateStatusData[date].timeout),
                        backgroundColor: 'rgba(245, 158, 11, 0.8)',
                        stack: 'Stack 0'
                    },
                    {
                        label: 'Cancelled',
                        data: dates.map(date => dateStatusData[date].cancelled),
                        backgroundColor: 'rgba(156, 163, 175, 0.8)',
                        stack: 'Stack 0'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Total Distribution'
                    },
                    tooltip: {
                        callbacks: {
                            afterTitle: function(tooltipItems) {
                                const date = tooltipItems[0].label;
                                const data = dateStatusData[date];
                                return `Total: ${data.total}`;
                            },
                            footer: function(tooltipItems) {
                                const date = tooltipItems[0].label;
                                const data = dateStatusData[date];
                                return [
                                    `Completed: ${data.completed}`,
                                    `Failed: ${data.failed}`,
                                    `Timeout: ${data.timeout}`,
                                    `Cancelled: ${data.cancelled}`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        title: {
                            display: true,
                            text: 'Date'
                        }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Executions'
                        }
                    }
                }
            }
        };
    }
    
    function getPerformanceMetricsChartConfig(data) {
        const metrics = {};
        data.forEach(item => {
            const hour = new Date(item._id.hour).toLocaleString();
            metrics[hour] = item.avg_duration || 0;
        });
        
        const labels = Object.keys(metrics).sort();
        const values = labels.map(label => metrics[label]);
        
        return {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Average Duration (ms)',
                    data: values,
                    borderColor: 'rgb(34, 197, 94)',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Performance Metrics Over Time'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Duration (ms)'
                        }
                    }
                }
            }
        };
    }
    
    function getSettingsTrendsChartConfig(data) {
        const settings = {};
        data.forEach(item => {
            const setting = `${item._id.setting_type}: ${item._id.value}`;
            settings[setting] = item.count || 1;
        });
        
        const sorted = Object.entries(settings)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10);
        
        return {
            type: 'bar',
            data: {
                labels: sorted.map(([setting]) => setting),
                datasets: [{
                    label: 'Users',
                    data: sorted.map(([, count]) => count),
                    backgroundColor: 'rgba(168, 85, 247, 0.5)',
                    borderColor: 'rgb(168, 85, 247)',
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Popular Settings'
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Number of Users'
                        }
                    }
                }
            }
        };
    }
    
    function getGenericChartConfig(data) {
        // For unknown projections, try to create a simple chart
        if (!data || data.length === 0) return null;
        
        // Try to find numeric fields for a simple bar chart
        const firstItem = data[0];
        const numericFields = Object.keys(firstItem).filter(key => 
            typeof firstItem[key] === 'number' && key !== '_id'
        );
        
        if (numericFields.length === 0) return null;
        
        const field = numericFields[0];
        const values = data.slice(0, 20).map(item => ({
            label: JSON.stringify(item._id),
            value: item[field]
        }));
        
        return {
            type: 'bar',
            data: {
                labels: values.map(v => v.label),
                datasets: [{
                    label: field,
                    data: values.map(v => v.value),
                    backgroundColor: 'rgba(59, 130, 246, 0.5)',
                    borderColor: 'rgb(59, 130, 246)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: `${field} Distribution`
                    }
                }
            }
        };
    }
    
    function flattenObject(obj, prefix = '') {
        const flattened = {};
        for (const key in obj) {
            const value = obj[key];
            const newKey = prefix ? `${prefix}.${key}` : key;
            
            if (value && typeof value === 'object' && !Array.isArray(value) && !(value instanceof Date)) {
                Object.assign(flattened, flattenObject(value, newKey));
            } else {
                flattened[newKey] = value;
            }
        }
        return flattened;
    }
    
    function formatCellValue(value) {
        if (value === null || value === undefined) return '-';
        if (typeof value === 'boolean') return value ? 'Yes' : 'No';
        if (typeof value === 'number') {
            // Check if it's a timestamp (10 digits)
            if (value > 1000000000 && value < 10000000000) {
                return new Date(value * 1000).toLocaleString();
            }
            return value.toLocaleString();
        }
        if (Array.isArray(value)) return value.join(', ');
        return String(value);
    }
    
    function formatTimestamp(timestamp) {
        if (!timestamp) return '-';
        return new Date(timestamp).toLocaleString();
    }
    
    function getTimeSince(timestamp) {
        if (!timestamp) return 'Never';
        const seconds = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
        
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }
</script>

<AdminLayout path="/admin/projections">
    <div class="container mx-auto px-4 pb-8">
        <div class="flex justify-between items-center mb-6">
            <h1 class="text-3xl font-bold">Event Projections</h1>
            
            <button
                on:click={() => {
                    isManualRefresh = true;
                    loadProjections();
                }}
                class="btn btn-primary flex items-center gap-2"
                disabled={loading}
            >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" class:animate-spin={loading}>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Refresh
            </button>
        </div>
        
        <div class="grid gap-4">
            {#each projections || [] as projection}
                <div class="card hover:shadow-lg transition-shadow duration-200">
                    <div class="p-6">
                        <div class="flex flex-col lg:flex-row lg:justify-between lg:items-start gap-4">
                            <div class="flex-1 min-w-0">
                                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default flex flex-wrap items-center gap-2">
                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                                    </svg>
                                    {projection.name}
                                    <span class={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-neutral-100 dark:bg-neutral-800 ${statusColors[projection.status]}`}>
                                        {projection.status}
                                    </span>
                                </h3>
                                
                                <p class="text-fg-muted dark:text-dark-fg-muted mt-2">{projection.description}</p>
                                
                                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
                                    <div class="min-w-0">
                                        <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Output Collection</p>
                                        <p class="font-mono text-sm break-all bg-neutral-100 dark:bg-neutral-800 px-2 py-1 rounded" 
                                           title={projection.output_collection}>
                                            {projection.output_collection}
                                        </p>
                                    </div>
                                    
                                    <div class="min-w-0">
                                        <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Last Updated</p>
                                        <p class="text-sm font-medium" title={formatTimestamp(projection.last_updated)}>
                                            {getTimeSince(projection.last_updated)}
                                        </p>
                                    </div>
                                    
                                    <div class="min-w-0">
                                        <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Last Processed</p>
                                        <p class="text-sm font-medium" title={formatTimestamp(projection.last_processed)}>
                                            {getTimeSince(projection.last_processed)}
                                        </p>
                                    </div>
                                    
                                    <div class="min-w-0">
                                        <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Source Events</p>
                                        <p class="text-sm font-medium">{projection.source_events.length} types</p>
                                    </div>
                                </div>
                                
                                {#if projection.error}
                                    <div class="mt-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-center gap-2">
                                        <svg class="w-4 h-4 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                        </svg>
                                        <span class="text-red-700 dark:text-red-300">{projection.error}</span>
                                    </div>
                                {/if}
                                
                                <details class="mt-4 group">
                                    <summary class="cursor-pointer text-sm font-medium text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors flex items-center gap-2">
                                        <svg class="w-4 h-4 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                                        </svg>
                                        Source Events ({projection.source_events?.length || 0})
                                    </summary>
                                    <div class="mt-3 p-3 bg-neutral-50 dark:bg-neutral-900 rounded-lg">
                                        <div class="flex flex-wrap gap-2">
                                            {#each projection.source_events || [] as event}
                                                <span class="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium bg-white dark:bg-dark-bg-alt text-fg-default dark:text-dark-fg-default border border-border-default dark:border-dark-border-default shadow-sm hover:shadow-md transition-shadow">
                                                    <svg class="w-3 h-3 mr-1.5 text-primary dark:text-primary-light" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                                                    </svg>
                                                    {event}
                                                </span>
                                            {/each}
                                        </div>
                                    </div>
                                </details>
                            </div>
                            
                            <div class="flex flex-row lg:flex-col gap-2 flex-wrap justify-end">
                                {#if projection.status === 'active'}
                                    <button
                                        on:click={() => manageProjection('stop', projection.name)}
                                        class="btn btn-sm btn-secondary-outline"
                                        disabled={loading}
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                        </svg>
                                        Stop
                                    </button>
                                {:else if projection.status === 'paused'}
                                    <button
                                        on:click={() => manageProjection('start', projection.name)}
                                        class="btn btn-sm btn-primary"
                                        disabled={loading}
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                        </svg>
                                        Start
                                    </button>
                                {/if}
                                
                                <button
                                    on:click={() => manageProjection('rebuild', projection.name)}
                                    class="btn btn-sm btn-secondary"
                                    disabled={loading || projection.status === 'rebuilding'}
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                    </svg>
                                    Rebuild
                                </button>
                                
                                <button
                                    on:click={() => queryProjection(projection.name)}
                                    class="btn btn-sm btn-secondary-outline"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                                    </svg>
                                    Query
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            {/each}
        </div>
    </div>

    {#if selectedProjection}
        <div class="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:p-0">
            <div class="fixed inset-0 bg-black bg-opacity-50" on:click={() => {
                selectedProjection = null;
                if (currentChart) {
                    currentChart.destroy();
                    currentChart = null;
                }
            }}></div>
            <div class="relative inline-block align-bottom bg-bg-alt dark:bg-dark-bg-alt rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-6xl sm:w-full max-h-[90vh] overflow-y-auto">
                <div class="p-6">
                    <div class="flex justify-between items-center mb-4">
                        <div>
                            <h3 class="font-bold text-xl text-fg-default dark:text-dark-fg-default">
                                {selectedProjection.name.replace(/_/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                            </h3>
                            <p class="text-sm text-fg-muted dark:text-dark-fg-muted">
                                Showing {selectedProjection.data.length} of {selectedProjection.total} records
                            </p>
                        </div>
                        <button
                            on:click={() => {
                                const jsonData = JSON.stringify(selectedProjection.data, null, 2);
                                navigator.clipboard.writeText(jsonData);
                                addNotification('JSON data copied to clipboard', 'success');
                            }}
                            class="btn btn-sm btn-secondary-outline flex items-center gap-2"
                            title="Copy raw JSON data"
                        >
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            Copy JSON
                        </button>
                    </div>
                    
                    {#if selectedProjection.data.length === 0}
                        <div class="bg-neutral-100 dark:bg-neutral-800 p-8 rounded text-center">
                            <svg class="w-12 h-12 mx-auto mb-4 text-fg-muted dark:text-dark-fg-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                            </svg>
                            <p class="text-fg-muted dark:text-dark-fg-muted mb-2">No data available for this projection</p>
                            <p class="text-sm text-fg-subtle dark:text-dark-fg-subtle">
                                This projection may be:
                            </p>
                            <ul class="text-sm text-fg-subtle dark:text-dark-fg-subtle mt-2 space-y-1">
                                <li>• Still processing initial data</li>
                                <li>• Paused or stopped</li>
                                <li>• Filtered by specific criteria</li>
                                <li>• Waiting for matching events</li>
                            </ul>
                        </div>
                    {:else}
                        <div class="bg-white dark:bg-neutral-900 rounded-lg p-4 border border-border-default dark:border-dark-border-default">
                            {#if chartLoaded}
                                <canvas id={`chart-${selectedProjection.name}`} width="400" height="400"></canvas>
                            {:else}
                                <div class="flex items-center justify-center h-96">
                                    <div class="text-center">
                                        <svg class="animate-spin h-8 w-8 mx-auto mb-4 text-primary" fill="none" viewBox="0 0 24 24">
                                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                        <p class="text-fg-muted dark:text-dark-fg-muted">Loading chart library...</p>
                                    </div>
                                </div>
                            {/if}
                        </div>
                        
                        <!-- Data table below chart -->
                        <div class="mt-6">
                            <h4 class="font-medium text-fg-default dark:text-dark-fg-default mb-3">Data Summary</h4>
                            <div class="overflow-x-auto">
                                <table class="w-full text-sm">
                                    <thead class="bg-neutral-50 dark:bg-neutral-800">
                                        <tr>
                                            {#if selectedProjection.data.length > 0}
                                                {#each Object.keys(flattenObject(selectedProjection.data[0])).slice(0, 5) as key}
                                                    <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">
                                                        {key.replace(/_/g, ' ')}
                                                    </th>
                                                {/each}
                                            {/if}
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-border-default dark:divide-dark-border-default">
                                        {#each selectedProjection.data.slice(-3) as row}
                                            <tr class="hover:bg-neutral-50 dark:hover:bg-neutral-800">
                                                {#each Object.values(flattenObject(row)).slice(0, 5) as value}
                                                    <td class="px-4 py-2 text-fg-default dark:text-dark-fg-default">
                                                        {formatCellValue(value)}
                                                    </td>
                                                {/each}
                                            </tr>
                                        {/each}
                                    </tbody>
                                </table>
                            </div>
                            {#if selectedProjection.data.length > 3}
                                <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-2">
                                    Showing last 3 of {selectedProjection.data.length} records
                                </p>
                            {/if}
                        </div>
                    {/if}
                    
                    <div class="mt-6 flex justify-end">
                        <button
                            on:click={() => {
                                selectedProjection = null;
                                if (currentChart) {
                                    currentChart.destroy();
                                    currentChart = null;
                                }
                            }}
                            class="btn btn-secondary-outline"
                        >
                            Close
                        </button>
                    </div>
                </div>
            </div>
        </div>
    {/if}
</AdminLayout>