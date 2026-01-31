<script lang="ts">
    import type { AdminUserOverview } from '$lib/api';
    import { formatTimestamp } from '$lib/formatters';
    import { getEventTypeColor, getEventTypeLabel } from '$lib/admin/events';
    import Modal from '$components/Modal.svelte';
    import Spinner from '$components/Spinner.svelte';

    interface Props {
        overview: AdminUserOverview | null;
        loading: boolean;
        open: boolean;
        onClose: () => void;
    }

    let { overview, loading, open, onClose }: Props = $props();

    const recentEvents = $derived(overview?.recent_events ?? []);
</script>

<Modal {open} title="User Overview" {onClose} size="lg">
    {#if loading}
        <div class="flex items-center justify-center py-10">
            <Spinner />
        </div>
    {:else if overview}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- User info -->
            <div>
                <h3 class="font-semibold mb-3 text-fg-default dark:text-dark-fg-default">Profile</h3>
                <div class="space-y-2 text-sm">
                    <div><span class="text-fg-muted dark:text-dark-fg-muted">User ID:</span> <span class="font-mono">{overview.user.user_id}</span></div>
                    <div><span class="text-fg-muted dark:text-dark-fg-muted">Username:</span> {overview.user.username}</div>
                    <div><span class="text-fg-muted dark:text-dark-fg-muted">Email:</span> {overview.user.email}</div>
                    <div><span class="text-fg-muted dark:text-dark-fg-muted">Role:</span> {overview.user.role}</div>
                    <div><span class="text-fg-muted dark:text-dark-fg-muted">Active:</span> {overview.user.is_active ? 'Yes' : 'No'}</div>
                    <div><span class="text-fg-muted dark:text-dark-fg-muted">Superuser:</span> {overview.user.is_superuser ? 'Yes' : 'No'}</div>
                </div>
                {#if overview.rate_limit_summary}
                    <div class="mt-4">
                        <h4 class="font-medium mb-2 text-fg-default dark:text-dark-fg-default">Rate Limits</h4>
                        <div class="text-sm space-y-1">
                            <div><span class="text-fg-muted dark:text-dark-fg-muted">Bypass:</span> {overview.rate_limit_summary.bypass_rate_limit ? 'Yes' : 'No'}</div>
                            <div><span class="text-fg-muted dark:text-dark-fg-muted">Global Multiplier:</span> {overview.rate_limit_summary.global_multiplier ?? 1.0}</div>
                            <div><span class="text-fg-muted dark:text-dark-fg-muted">Custom Rules:</span> {overview.rate_limit_summary.has_custom_limits ? 'Yes' : 'No'}</div>
                        </div>
                    </div>
                {/if}
            </div>

            <!-- Stats -->
            <div>
                <h3 class="font-semibold mb-3 text-fg-default dark:text-dark-fg-default">Execution Stats (last 24h)</h3>
                <div class="grid grid-cols-2 gap-3">
                    <div class="p-3 rounded-lg bg-green-50 dark:bg-green-900/20">
                        <div class="text-xs text-green-700 dark:text-green-300">Succeeded</div>
                        <div class="text-xl font-semibold text-green-800 dark:text-green-200">{overview.derived_counts.succeeded}</div>
                    </div>
                    <div class="p-3 rounded-lg bg-red-50 dark:bg-red-900/20">
                        <div class="text-xs text-red-700 dark:text-red-300">Failed</div>
                        <div class="text-xl font-semibold text-red-800 dark:text-red-200">{overview.derived_counts.failed}</div>
                    </div>
                    <div class="p-3 rounded-lg bg-yellow-50 dark:bg-yellow-900/20">
                        <div class="text-xs text-yellow-700 dark:text-yellow-300">Timeout</div>
                        <div class="text-xl font-semibold text-yellow-800 dark:text-yellow-200">{overview.derived_counts.timeout}</div>
                    </div>
                    <div class="p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800">
                        <div class="text-xs text-neutral-700 dark:text-neutral-300">Cancelled</div>
                        <div class="text-xl font-semibold text-neutral-900 dark:text-neutral-100">{overview.derived_counts.cancelled}</div>
                    </div>
                </div>
                <div class="mt-3 text-sm text-fg-muted dark:text-dark-fg-muted">
                    Terminal Total: <span class="font-semibold text-fg-default dark:text-dark-fg-default">{overview.derived_counts.terminal_total}</span>
                </div>
                <div class="mt-2 text-sm text-fg-muted dark:text-dark-fg-muted">
                    Total Events: <span class="font-semibold text-fg-default dark:text-dark-fg-default">{overview.stats.total_events}</span>
                </div>
            </div>
        </div>

        {#if recentEvents.length > 0}
            <div class="mt-6">
                <h3 class="font-semibold mb-2 text-fg-default dark:text-dark-fg-default">Recent Execution Events</h3>
                <div class="space-y-1 max-h-48 overflow-auto">
                    {#each recentEvents as ev}
                        <div class="flex justify-between items-center p-2 bg-neutral-50 dark:bg-neutral-800 rounded">
                            <div class="text-sm">
                                <span class={getEventTypeColor(ev.event_type)}>{getEventTypeLabel(ev.event_type) || ev.event_type}</span>
                                <span class="ml-2 font-mono text-xs text-fg-muted dark:text-dark-fg-muted">{ev.aggregate_id || '-'}</span>
                            </div>
                            <div class="text-xs text-fg-muted dark:text-dark-fg-muted">{formatTimestamp(ev.timestamp)}</div>
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    {:else}
        <div class="text-sm text-fg-muted dark:text-dark-fg-muted">No data available</div>
    {/if}

    {#snippet footer()}
        <a href="/admin/users" class="btn btn-outline">Open User Management</a>
    {/snippet}
</Modal>
