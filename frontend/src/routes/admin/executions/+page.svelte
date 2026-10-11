<script lang="ts">
    import { ExecutionStatus, QueuePriority } from '#lib/api/index.ts';
    import Spinner from '#components/Spinner.svelte';
    import { ExecutionsTable } from '#components/admin/executions/index.ts';
    import { RefreshCw } from '@lucide/svelte';
    import { STATS_BG_COLORS, STATS_TEXT_COLORS } from '#lib/admin/constants.ts';
    import { createExecutionsStore } from '#lib/admin/stores/executionsStore.svelte.ts';
    import { formatEnumLabel } from '#lib/formatters.ts';

    const store = createExecutionsStore();

    const priorityOptions = Object.values(QueuePriority);

    let fetching = $derived(store.list.isFetching || store.queueStatus.isFetching);
    let queueStatus = $derived(store.queueStatus.data);
</script>

<div class="container mx-auto px-2 sm:px-4 pb-8">
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">Execution Management</h1>
        <button
            type="button"
            onclick={() => store.refresh()}
            class="btn btn-secondary-outline flex items-center gap-2"
            disabled={fetching}
        >
            {#if fetching}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
        </button>
    </div>

    <!-- Queue Status Cards -->
    {#if queueStatus}
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div class="card p-4 {STATS_BG_COLORS.blue}">
                <div class="text-sm {STATS_TEXT_COLORS.blue} font-medium">Queue Depth</div>
                <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">
                    {queueStatus.queue_depth}
                </div>
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
                <label for="status-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                    >Status</label
                >
                <select id="status-filter" bind:value={store.statusFilter} class="form-select-standard">
                    <option value="all">All</option>
                    {#each Object.values(ExecutionStatus) as status (status)}
                        <option value={status}>{formatEnumLabel(status)}</option>
                    {/each}
                </select>
            </div>
            <div>
                <label
                    for="priority-filter"
                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Priority</label
                >
                <select id="priority-filter" bind:value={store.priorityFilter} class="form-select-standard">
                    <option value="all">All</option>
                    {#each priorityOptions as p}
                        <option value={p}>{p}</option>
                    {/each}
                </select>
            </div>
            <div>
                <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                    >User ID</label
                >
                <input
                    id="user-search"
                    type="text"
                    bind:value={store.userSearch}
                    placeholder="Filter by user ID"
                    class="form-input-standard"
                />
            </div>
            <button type="button" onclick={() => store.resetFilters()} class="btn btn-secondary-outline text-sm"
                >Reset</button
            >
        </div>
    </div>

    <!-- Table -->
    <div class="card">
        <div class="p-3 sm:p-6">
            <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                Executions ({store.total})
            </h3>

            <ExecutionsTable
                executions={store.executions}
                rowCount={store.total}
                bind:pagination={store.pagination}
                loading={store.list.isPending}
                onPriorityChange={(executionId, priority) =>
                    store.updatePriority.mutate({ path: { execution_id: executionId }, body: { priority } })}
            />
        </div>
    </div>
</div>
