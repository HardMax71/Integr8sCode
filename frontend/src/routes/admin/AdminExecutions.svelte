<script lang="ts">
    import { onMount, untrack } from 'svelte';
    import type { QueuePriority } from '$lib/api';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Spinner from '$components/Spinner.svelte';
    import Pagination from '$components/Pagination.svelte';
    import { RefreshCw } from '@lucide/svelte';
    import { STATS_BG_COLORS, STATS_TEXT_COLORS } from '$lib/admin/constants';
    import { createExecutionsStore } from '$lib/admin/stores/executionsStore.svelte';
    import { formatTimestamp, truncate } from '$lib/formatters';

    const store = createExecutionsStore();

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

    let totalPages = $derived(Math.ceil(store.total / store.pagination.pageSize));

    let prevFilters = $state({ status: store.statusFilter, priority: store.priorityFilter, search: store.userSearch });

    $effect(() => {
        const current = { status: store.statusFilter, priority: store.priorityFilter, search: store.userSearch };
        if (current.status !== prevFilters.status || current.priority !== prevFilters.priority || current.search !== prevFilters.search) {
            prevFilters = current;
            untrack(() => {
                store.pagination.currentPage = 1;
                store.loadExecutions();
            });
        }
    });

    onMount(() => {
        store.loadData();
    });
</script>

<AdminLayout path="/admin/executions">
    <div class="container mx-auto px-2 sm:px-4 pb-8">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">Execution Management</h1>
            <button type="button" onclick={() => store.loadData()} class="btn btn-outline flex items-center gap-2" disabled={store.loading}>
                {#if store.loading}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
            </button>
        </div>

        <!-- Queue Status Cards -->
        {#if store.queueStatus}
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
                <div class="card p-4 {STATS_BG_COLORS.blue}">
                    <div class="text-sm {STATS_TEXT_COLORS.blue} font-medium">Queue Depth</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">{store.queueStatus.queue_depth}</div>
                </div>
                <div class="card p-4 {STATS_BG_COLORS.green}">
                    <div class="text-sm {STATS_TEXT_COLORS.green} font-medium">Active</div>
                    <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">
                        {store.queueStatus.active_count} / {store.queueStatus.max_concurrent}
                    </div>
                </div>
                <div class="card p-4 {STATS_BG_COLORS.purple}">
                    <div class="text-sm {STATS_TEXT_COLORS.purple} font-medium">By Priority</div>
                    <div class="text-sm text-fg-default dark:text-dark-fg-default mt-1">
                        {#each Object.entries(store.queueStatus.by_priority) as [priority, count]}
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
                    <select id="status-filter" bind:value={store.statusFilter} class="input-field">
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
                    <select id="priority-filter" bind:value={store.priorityFilter} class="input-field">
                        <option value="all">All</option>
                        {#each priorityOptions as p}
                            <option value={p}>{p}</option>
                        {/each}
                    </select>
                </div>
                <div>
                    <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">User ID</label>
                    <input id="user-search" type="text" bind:value={store.userSearch} placeholder="Filter by user ID" class="input-field" />
                </div>
                <button type="button" onclick={() => store.resetFilters()} class="btn btn-outline text-sm">Reset</button>
            </div>
        </div>

        <!-- Table -->
        <div class="card">
            <div class="p-3 sm:p-6">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                    Executions ({store.total})
                </h3>

                {#if store.loading && store.executions.length === 0}
                    <div class="flex justify-center py-8"><Spinner size="large" /></div>
                {:else if store.executions.length === 0}
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
                                {#each store.executions as exec}
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
                                                onchange={(e) => store.updatePriority(exec.execution_id, (e.target as HTMLSelectElement).value as QueuePriority)}
                                                class="input-field text-xs py-1 px-2"
                                                aria-label="Priority for {exec.execution_id}"
                                            >
                                                {#each priorityOptions as p}
                                                    <option value={p}>{p}</option>
                                                {/each}
                                            </select>
                                        </td>
                                        <td class="p-2 text-xs">{formatTimestamp(exec.created_at)}</td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                {/if}

                {#if totalPages > 1}
                    <div class="mt-4 border-t divider pt-4">
                        <Pagination
                            currentPage={store.pagination.currentPage}
                            {totalPages}
                            totalItems={store.total}
                            pageSize={store.pagination.pageSize}
                            onPageChange={(page) => store.pagination.handlePageChange(page, () => store.loadExecutions())}
                            onPageSizeChange={(size) => store.pagination.handlePageSizeChange(size, () => store.loadExecutions())}
                            pageSizeOptions={[10, 20, 50, 100]}
                            itemName="executions"
                        />
                    </div>
                {/if}
            </div>
        </div>
    </div>
</AdminLayout>
