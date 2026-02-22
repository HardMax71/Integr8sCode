<script lang="ts">
    import { onMount } from 'svelte';
    import {
        listExecutionsApiV1AdminExecutionsGet,
        updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut,
        getQueueStatusApiV1AdminExecutionsQueueGet,
        type AdminExecutionResponse,
        type QueueStatusResponse,
        type QueuePriority,
        type ExecutionStatus,
    } from '$lib/api';
    import { unwrap, unwrapOr } from '$lib/api-interceptors';
    import { toast } from 'svelte-sonner';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Spinner from '$components/Spinner.svelte';
    import Pagination from '$components/Pagination.svelte';
    import { RefreshCw } from '@lucide/svelte';
    import { STATS_BG_COLORS, STATS_TEXT_COLORS } from '$lib/admin/constants';

    let executions = $state<AdminExecutionResponse[]>([]);
    let total = $state(0);
    let loading = $state(false);
    let queueStatus = $state<QueueStatusResponse | null>(null);

    // Filters
    let statusFilter = $state<'all' | ExecutionStatus>('all');
    let priorityFilter = $state<'all' | QueuePriority>('all');
    let userSearch = $state('');

    // Pagination
    let currentPage = $state(1);
    let pageSize = $state(20);

    let totalPages = $derived(Math.ceil(total / pageSize));

    onMount(() => {
        loadQueueStatus();
        const interval = setInterval(loadData, 5000);
        return () => clearInterval(interval);
    });

    async function loadData(): Promise<void> {
        await Promise.all([loadExecutions(), loadQueueStatus()]);
    }

    async function loadExecutions(): Promise<void> {
        loading = true;
        const data = unwrapOr(await listExecutionsApiV1AdminExecutionsGet({
            query: {
                limit: pageSize,
                skip: (currentPage - 1) * pageSize,
                status: statusFilter !== 'all' ? statusFilter : undefined,
                priority: priorityFilter !== 'all' ? priorityFilter : undefined,
                user_id: userSearch || undefined,
            },
        }), null);
        executions = data?.executions || [];
        total = data?.total || 0;
        loading = false;
    }

    async function loadQueueStatus(): Promise<void> {
        const data = unwrapOr(await getQueueStatusApiV1AdminExecutionsQueueGet({}), null);
        if (data) {
            queueStatus = data;
        }
    }

    async function updatePriority(executionId: string, newPriority: QueuePriority): Promise<void> {
        unwrap(await updatePriorityApiV1AdminExecutionsExecutionIdPriorityPut({
            path: { execution_id: executionId },
            body: { priority: newPriority },
        }));
        toast.success(`Priority updated to ${newPriority}`);
        await loadData();
    }

    function handlePageChange(page: number): void { currentPage = page; loadExecutions(); }
    function handlePageSizeChange(size: number): void { pageSize = size; currentPage = 1; loadExecutions(); }

    function resetFilters(): void {
        statusFilter = 'all';
        priorityFilter = 'all';
        userSearch = '';
    }

    const statusColors: Record<string, string> = {
        queued: 'badge-info',
        scheduled: 'badge-info',
        running: 'badge-warning',
        completed: 'badge-success',
        failed: 'badge-danger',
        timeout: 'badge-danger',
        cancelled: 'badge-neutral',
        error: 'badge-danger',
    };

    const priorityOptions: QueuePriority[] = ['critical', 'high', 'normal', 'low', 'background'];

    function formatDate(dateStr: string): string {
        return new Date(dateStr).toLocaleString();
    }

    function truncate(text: string, maxLen: number): string {
        return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
    }

    // Reset page when filters change
    $effect(() => {
        void statusFilter;
        void priorityFilter;
        void userSearch;
        currentPage = 1;
        loadExecutions();
    });
</script>

<AdminLayout path="/admin/executions">
    <div class="container mx-auto px-2 sm:px-4 pb-8">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">Execution Management</h1>
            <button type="button" onclick={() => loadData()} class="btn btn-outline flex items-center gap-2" disabled={loading}>
                {#if loading}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
            </button>
        </div>

        <!-- Queue Status Cards -->
        {#if queueStatus}
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
                <div class="card p-4 {STATS_BG_COLORS.blue}">
                    <div class="text-sm {STATS_TEXT_COLORS.blue} font-medium">Queue Depth</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{queueStatus.queue_depth}</div>
                </div>
                <div class="card p-4 {STATS_BG_COLORS.green}">
                    <div class="text-sm {STATS_TEXT_COLORS.green} font-medium">Active</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">
                        {queueStatus.active_count} / {queueStatus.max_concurrent}
                    </div>
                </div>
                <div class="card p-4 {STATS_BG_COLORS.purple}">
                    <div class="text-sm {STATS_TEXT_COLORS.purple} font-medium">By Priority</div>
                    <div class="text-sm text-fg-default dark:text-dark-fg-default mt-1">
                        {#each Object.entries(queueStatus.by_priority) as [priority, count]}
                            <span class="mr-2">{priority}: {count}</span>
                        {:else}
                            <span class="text-fg-muted dark:text-dark-fg-muted">Empty</span>
                        {/each}
                    </div>
                </div>
            </div>
        {/if}

        <!-- Filters -->
        <div class="card mb-6">
            <div class="p-4 flex flex-wrap gap-4 items-end">
                <div>
                    <label for="status-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Status</label>
                    <select id="status-filter" bind:value={statusFilter} class="input-field">
                        <option value="all">All</option>
                        <option value="queued">Queued</option>
                        <option value="scheduled">Scheduled</option>
                        <option value="running">Running</option>
                        <option value="completed">Completed</option>
                        <option value="failed">Failed</option>
                        <option value="timeout">Timeout</option>
                        <option value="cancelled">Cancelled</option>
                        <option value="error">Error</option>
                    </select>
                </div>
                <div>
                    <label for="priority-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Priority</label>
                    <select id="priority-filter" bind:value={priorityFilter} class="input-field">
                        <option value="all">All</option>
                        {#each priorityOptions as p}
                            <option value={p}>{p}</option>
                        {/each}
                    </select>
                </div>
                <div>
                    <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">User ID</label>
                    <input id="user-search" type="text" bind:value={userSearch} placeholder="Filter by user ID" class="input-field" />
                </div>
                <button type="button" onclick={resetFilters} class="btn btn-outline text-sm">Reset</button>
            </div>
        </div>

        <!-- Table -->
        <div class="card">
            <div class="p-3 sm:p-6">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                    Executions ({total})
                </h3>

                {#if loading && executions.length === 0}
                    <div class="flex justify-center py-8"><Spinner size="large" /></div>
                {:else if executions.length === 0}
                    <p class="text-center py-8 text-fg-muted dark:text-dark-fg-muted">No executions found</p>
                {:else}
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead>
                                <tr class="border-b divider">
                                    <th class="text-left p-2">ID</th>
                                    <th class="text-left p-2">User</th>
                                    <th class="text-left p-2">Language</th>
                                    <th class="text-left p-2">Status</th>
                                    <th class="text-left p-2">Priority</th>
                                    <th class="text-left p-2">Created</th>
                                </tr>
                            </thead>
                            <tbody>
                                {#each executions as exec}
                                    <tr class="border-b divider hover:bg-bg-subtle dark:hover:bg-dark-bg-subtle">
                                        <td class="p-2 font-mono text-xs">{truncate(exec.execution_id, 12)}</td>
                                        <td class="p-2 text-xs">{exec.user_id ? truncate(exec.user_id, 12) : '-'}</td>
                                        <td class="p-2">{exec.lang} {exec.lang_version}</td>
                                        <td class="p-2">
                                            <span class="badge {statusColors[exec.status] || 'badge-neutral'}">{exec.status}</span>
                                        </td>
                                        <td class="p-2">
                                            <select
                                                value={exec.priority}
                                                onchange={(e) => updatePriority(exec.execution_id, (e.target as HTMLSelectElement).value as QueuePriority)}
                                                class="input-field text-xs py-1 px-2"
                                                aria-label="Priority for {exec.execution_id}"
                                            >
                                                {#each priorityOptions as p}
                                                    <option value={p}>{p}</option>
                                                {/each}
                                            </select>
                                        </td>
                                        <td class="p-2 text-xs">{formatDate(exec.created_at)}</td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                {/if}

                {#if totalPages > 1}
                    <div class="mt-4 border-t divider pt-4">
                        <Pagination
                            {currentPage}
                            {totalPages}
                            totalItems={total}
                            {pageSize}
                            onPageChange={handlePageChange}
                            onPageSizeChange={handlePageSizeChange}
                            pageSizeOptions={[10, 20, 50, 100]}
                            itemName="executions"
                        />
                    </div>
                {/if}
            </div>
        </div>
    </div>
</AdminLayout>
