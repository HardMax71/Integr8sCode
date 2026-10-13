<script lang="ts">
    import { resolve } from '$app/paths';
    import { createQuery } from '@tanstack/svelte-query';
    import { getUserOverviewApiV1AdminUsersUserIdOverviewGetOptions } from '#lib/api/index.ts';
    import { fieldTitle, formatBoolean, formatTimestamp } from '#lib/formatters.ts';
    import { getEventTypeColor } from '#lib/admin/events/index.ts';
    import Modal from '#components/Modal.svelte';
    import Spinner from '#components/Spinner.svelte';

    interface Props {
        userId: string;
        onClose: () => void;
    }

    let { userId, onClose }: Props = $props();

    const query = createQuery(() =>
        getUserOverviewApiV1AdminUsersUserIdOverviewGetOptions({ path: { user_id: userId } }),
    );
    const overview = $derived(query.data);

    const recentEvents = $derived(overview?.recent_events ?? []);
</script>

<Modal open title="User Overview" {onClose} size="lg">
    {#if query.isPending}
        <div class="flex items-center justify-center py-10">
            <Spinner />
        </div>
    {:else if overview}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
                <h3 class="font-semibold mb-3 text-fg">{fieldTitle('user')}</h3>
                <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm [&>dt]:text-fg-muted">
                    <dt>{fieldTitle('user_id')}</dt>
                    <dd class="font-mono">{overview.user.user_id}</dd>
                    <dt>{fieldTitle('username')}</dt>
                    <dd>{overview.user.username}</dd>
                    <dt>{fieldTitle('email')}</dt>
                    <dd>{overview.user.email}</dd>
                    <dt>{fieldTitle('role')}</dt>
                    <dd>{overview.user.role}</dd>
                    <dt>{fieldTitle('is_active')}</dt>
                    <dd>{formatBoolean(overview.user.is_active)}</dd>
                    <dt>{fieldTitle('is_superuser')}</dt>
                    <dd>{formatBoolean(overview.user.is_superuser)}</dd>
                </dl>
                <div class="mt-4">
                    <h4 class="font-medium mb-2 text-fg">
                        {fieldTitle('rate_limit_summary')}
                    </h4>
                    <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm [&>dt]:text-fg-muted">
                        <dt>{fieldTitle('bypass_rate_limit')}</dt>
                        <dd>{formatBoolean(overview.rate_limit_summary.bypass_rate_limit)}</dd>
                        <dt>{fieldTitle('global_multiplier')}</dt>
                        <dd>{overview.rate_limit_summary.global_multiplier}</dd>
                        <dt>{fieldTitle('has_custom_limits')}</dt>
                        <dd>{formatBoolean(overview.rate_limit_summary.has_custom_limits)}</dd>
                    </dl>
                </div>
            </div>

            <div>
                <h3 class="font-semibold text-fg">{fieldTitle('derived_counts')}</h3>
                <p class="text-xs text-fg-muted mb-3">Last 24 hours</p>
                <div class="grid grid-cols-2 gap-3">
                    <div class="p-3 rounded-lg bg-success-soft">
                        <div class="text-xs text-success">{fieldTitle('succeeded')}</div>
                        <div class="text-xl font-semibold text-success">
                            {overview.derived_counts.succeeded}
                        </div>
                    </div>
                    <div class="p-3 rounded-lg bg-danger-soft">
                        <div class="text-xs text-danger">{fieldTitle('failed')}</div>
                        <div class="text-xl font-semibold text-danger">
                            {overview.derived_counts.failed}
                        </div>
                    </div>
                    <div class="p-3 rounded-lg bg-warning-soft">
                        <div class="text-xs text-warning">{fieldTitle('timeout')}</div>
                        <div class="text-xl font-semibold text-warning">
                            {overview.derived_counts.timeout}
                        </div>
                    </div>
                    <div class="p-3 rounded-lg bg-muted">
                        <div class="text-xs text-fg">{fieldTitle('cancelled')}</div>
                        <div class="text-xl font-semibold text-fg">
                            {overview.derived_counts.cancelled}
                        </div>
                    </div>
                </div>
                <dl
                    class="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm [&>dt]:text-fg-muted [&>dd]:font-semibold"
                >
                    <dt>{fieldTitle('terminal_total')}</dt>
                    <dd>{overview.derived_counts.terminal_total}</dd>
                    <dt>{fieldTitle('total_events')}</dt>
                    <dd>{overview.stats.total_events}</dd>
                </dl>
            </div>
        </div>

        {#if recentEvents.length > 0}
            <div class="mt-6">
                <h3 class="font-semibold mb-2 text-fg">
                    {fieldTitle('recent_events')}
                </h3>
                <div class="space-y-1 max-h-48 overflow-auto">
                    {#each recentEvents as ev (ev.event_id)}
                        <div class="flex justify-between items-center p-2 bg-muted rounded">
                            <div class="text-sm">
                                <span class={getEventTypeColor(ev.event_type)}>{ev.event_type}</span>
                                <span class="ml-2 font-mono text-xs text-fg-muted">{ev.aggregate_id || '-'}</span>
                            </div>
                            <div class="text-xs text-fg-muted">
                                {formatTimestamp(ev.timestamp)}
                            </div>
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    {:else}
        <div class="text-sm text-fg-muted">No data available</div>
    {/if}

    {#snippet footer()}
        <a href={resolve('/admin/users')} class="btn btn-secondary-outline">Open User Management</a>
    {/snippet}
</Modal>
