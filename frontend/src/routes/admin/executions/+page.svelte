<script lang="ts">
    import { createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
    import {
        ExecutionStatus,
        QueuePriority,
        getQueueStatusApiV1AdminExecutionsQueueGetOptions,
        getQueueStatusApiV1AdminExecutionsQueueGetQueryKey,
        listExecutionsApiV1AdminExecutionsGetOptions,
        listExecutionsApiV1AdminExecutionsGetQueryKey,
        type ListExecutionsApiV1AdminExecutionsGetData,
    } from '#lib/api/index.ts';
    import Spinner from '#components/Spinner.svelte';
    import { ExecutionsTable } from '#components/admin/executions/index.ts';
    import { RefreshCw } from '@lucide/svelte';
    import { STATS_BG_COLORS, STATS_TEXT_COLORS } from '#lib/admin/constants.ts';
    import { fieldTitle } from '#lib/formatters.ts';

    type ExecutionFilters = Required<
        Pick<NonNullable<ListExecutionsApiV1AdminExecutionsGetData['query']>, 'status' | 'priority' | 'user_id'>
    >;

    const POLL_INTERVAL_MS = 5_000;
    const noFilters = (): ExecutionFilters => ({ status: null, priority: null, user_id: null });
    let filters = $state(noFilters());

    // A new filter goes back to the first page, since the old one may not exist under it
    let pageSize = $state(20);
    let pageIndex = $derived.by(() => {
        void { ...filters };
        return 0;
    });

    const queryClient = useQueryClient();
    const list = createQuery(() => ({
        ...listExecutionsApiV1AdminExecutionsGetOptions({
            query: { ...filters, user_id: filters.user_id || null, limit: pageSize, skip: pageIndex * pageSize },
        }),
        placeholderData: keepPreviousData,
        refetchInterval: POLL_INTERVAL_MS,
    }));
    const queue = createQuery(() => ({
        ...getQueueStatusApiV1AdminExecutionsQueueGetOptions(),
        refetchInterval: POLL_INTERVAL_MS,
    }));
    const fetching = $derived(list.isFetching || queue.isFetching);
    const total = $derived(list.data?.total ?? 0);

    function refresh(): void {
        void queryClient.invalidateQueries({ queryKey: listExecutionsApiV1AdminExecutionsGetQueryKey() });
        void queryClient.invalidateQueries({ queryKey: getQueueStatusApiV1AdminExecutionsQueueGetQueryKey() });
    }
</script>

<div class="container mx-auto px-2 sm:px-4 pb-8">
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">Execution Management</h1>
        <button
            type="button"
            onclick={refresh}
            class="btn btn-secondary-outline flex items-center gap-2"
            disabled={fetching}
        >
            {#if fetching}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
        </button>
    </div>

    <!-- Queue Status Cards -->
    {#if queue.data}
        {@const queueStatus = queue.data}
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div class="card p-4 {STATS_BG_COLORS.blue}">
                <div class="text-sm {STATS_TEXT_COLORS.blue} font-medium">{fieldTitle('queue_depth')}</div>
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
                <div class="text-sm {STATS_TEXT_COLORS.purple} font-medium">{fieldTitle('by_priority')}</div>
                <div class="text-sm text-fg-default dark:text-dark-fg-default mt-1">
                    {#each Object.entries(queueStatus.by_priority) as [priority, count] (priority)}
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
                    >{fieldTitle('status')}</label
                >
                <select id="status-filter" bind:value={filters.status} class="form-select-standard">
                    <option value={null}>All</option>
                    {#each Object.values(ExecutionStatus) as status (status)}
                        <option value={status}>{status}</option>
                    {/each}
                </select>
            </div>
            <div>
                <label
                    for="priority-filter"
                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                    >{fieldTitle('priority')}</label
                >
                <select id="priority-filter" bind:value={filters.priority} class="form-select-standard">
                    <option value={null}>All</option>
                    {#each Object.values(QueuePriority) as p (p)}
                        <option value={p}>{p}</option>
                    {/each}
                </select>
            </div>
            <div>
                <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                    >{fieldTitle('user_id')}</label
                >
                <input id="user-search" type="text" bind:value={filters.user_id} class="form-input-standard" />
            </div>
            <button type="button" onclick={() => (filters = noFilters())} class="btn btn-secondary-outline text-sm"
                >Reset</button
            >
        </div>
    </div>

    <!-- Table -->
    <div class="card">
        <div class="p-3 sm:p-6">
            <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                Executions ({total})
            </h3>

            <ExecutionsTable
                executions={list.data?.executions ?? []}
                rowCount={total}
                bind:pagination={
                    () => ({ pageIndex, pageSize }),
                    (next) => {
                        pageSize = next.pageSize;
                        pageIndex = next.pageIndex;
                    }
                }
                loading={list.isPending}
            />
        </div>
    </div>
</div>
