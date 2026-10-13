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
        <h1>Execution Management</h1>
        <button type="button" onclick={refresh} class="btn btn-secondary-outline gap-2" disabled={fetching}>
            {#if fetching}<Spinner size="small" />{:else}<RefreshCw class="size-4" />{/if}Refresh
        </button>
    </div>

    {#if queue.data}
        {@const queueStatus = queue.data}
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <dl class="card stat p-4 bg-info-soft">
                <dt class="font-medium text-info">{fieldTitle('queue_depth')}</dt>
                <dd>{queueStatus.queue_depth}</dd>
            </dl>
            <dl class="card stat p-4 bg-success-soft">
                <dt class="font-medium text-success">{fieldTitle('active_count')}</dt>
                <dd>{queueStatus.active_count} / {queueStatus.max_concurrent}</dd>
            </dl>
            <dl class="card stat p-4 bg-purple-soft">
                <dt class="font-medium text-purple">{fieldTitle('by_priority')}</dt>
                <dd class="text-sm font-normal">
                    {#each Object.entries(queueStatus.by_priority) as [priority, count] (priority)}
                        <span class="mr-2">{priority}: {count}</span>
                    {:else}
                        <span class="text-fg-muted">Empty</span>
                    {/each}
                </dd>
            </dl>
        </div>
    {/if}

    <div class="card mb-6">
        <div class="p-4 flex flex-wrap gap-4 items-end">
            <div class="field">
                <label for="status-filter">{fieldTitle('status')}</label>
                <select id="status-filter" bind:value={filters.status} class="form-select-standard">
                    <option value={null}>All</option>
                    {#each Object.values(ExecutionStatus) as status (status)}
                        <option value={status}>{status}</option>
                    {/each}
                </select>
            </div>
            <div class="field">
                <label for="priority-filter">{fieldTitle('priority')}</label>
                <select id="priority-filter" bind:value={filters.priority} class="form-select-standard">
                    <option value={null}>All</option>
                    {#each Object.values(QueuePriority) as p (p)}
                        <option value={p}>{p}</option>
                    {/each}
                </select>
            </div>
            <div class="field">
                <label for="user-search">{fieldTitle('user_id')}</label>
                <input id="user-search" type="text" bind:value={filters.user_id} class="form-input-standard" />
            </div>
            <button type="button" onclick={() => (filters = noFilters())} class="btn btn-secondary-outline text-sm"
                >Reset</button
            >
        </div>
    </div>

    <div class="card">
        <div class="p-3 sm:p-6">
            <h3 class="text-lg font-semibold mb-4">
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
