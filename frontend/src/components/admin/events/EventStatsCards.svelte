<script lang="ts">
    import type { EventStatsResponse } from '../../../lib/api';

    interface Props {
        stats: EventStatsResponse | null;
        totalEvents: number;
    }

    let { stats, totalEvents }: Props = $props();
</script>

{#if stats}
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
        <div class="card p-4">
            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Events (Last 24h)</div>
            <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">
                {stats?.total_events?.toLocaleString() || '0'}
            </div>
            <div class="text-xs text-fg-muted dark:text-dark-fg-muted">
                of {totalEvents?.toLocaleString() || '0'} total
            </div>
        </div>

        <div class="card p-4">
            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Error Rate (24h)</div>
            <div class="text-2xl font-bold {stats?.error_rate > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}">
                {stats?.error_rate || 0}%
            </div>
        </div>

        <div class="card p-4">
            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Avg Execution Time (24h)</div>
            <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">
                {stats?.avg_processing_time ? stats.avg_processing_time.toFixed(2) : '0'}s
            </div>
        </div>

        <div class="card p-4">
            <div class="text-sm text-fg-muted dark:text-dark-fg-muted mb-1">Active Users (24h)</div>
            <div class="text-2xl font-bold text-fg-default dark:text-dark-fg-default">
                {stats?.top_users?.length || 0}
            </div>
            <div class="text-xs text-fg-muted dark:text-dark-fg-muted">with events</div>
        </div>
    </div>
{/if}
