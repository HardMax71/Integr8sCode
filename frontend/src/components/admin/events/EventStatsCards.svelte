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
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <dl class="card stat p-4">
            <dt>{fieldTitle('total_events')}</dt>
            <dd>{stats.total_events.toLocaleString()}</dd>
            <dd class="mt-0 text-xs font-normal text-fg-muted">of {totalEvents.toLocaleString()} total</dd>
        </dl>
        <dl class="card stat p-4">
            <dt>{fieldTitle('error_rate')}</dt>
            <dd class={stats.error_rate > 0 ? 'text-danger' : 'text-success'}>{stats.error_rate}%</dd>
        </dl>
        <dl class="card stat p-4">
            <dt>{fieldTitle('avg_processing_time')}</dt>
            <dd>{stats.avg_processing_time.toFixed(2)}s</dd>
        </dl>
        <dl class="card stat p-4">
            <dt>{fieldTitle('top_users')}</dt>
            <dd>{stats.top_users.length}</dd>
        </dl>
    </div>
{/if}
