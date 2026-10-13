<script lang="ts">
    import type { EventStatsResponse } from '#lib/api/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';

    interface Props {
        stats: EventStatsResponse | null;
        totalEvents: number;
    }

    let { stats, totalEvents }: Props = $props();
</script>

{#if stats}
    <p class="text-xs text-fg-muted mb-2">Last 24 hours</p>
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
        <div class="card p-4">
            <div class="text-sm text-fg-muted mb-1">{fieldTitle('total_events')}</div>
            <div class="text-2xl font-bold text-fg">
                {stats.total_events.toLocaleString()}
            </div>
            <div class="text-xs text-fg-muted">
                of {totalEvents.toLocaleString()} total
            </div>
        </div>

        <div class="card p-4">
            <div class="text-sm text-fg-muted mb-1">{fieldTitle('error_rate')}</div>
            <div class="text-2xl font-bold {stats.error_rate > 0 ? 'text-danger' : 'text-success'}">
                {stats.error_rate}%
            </div>
        </div>

        <div class="card p-4">
            <div class="text-sm text-fg-muted mb-1">{fieldTitle('avg_processing_time')}</div>
            <div class="text-2xl font-bold text-fg">
                {stats.avg_processing_time.toFixed(2)}s
            </div>
        </div>

        <div class="card p-4">
            <div class="text-sm text-fg-muted mb-1">{fieldTitle('top_users')}</div>
            <div class="text-2xl font-bold text-fg">
                {stats.top_users.length}
            </div>
        </div>
    </div>
{/if}
