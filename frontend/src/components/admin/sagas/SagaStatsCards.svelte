<script lang="ts">
    import { SagaState, type SagaStatusResponse } from '#lib/api/index.ts';
    import { SAGA_STATES } from '#lib/admin/sagas/index.ts';

    interface Props {
        sagas: SagaStatusResponse[];
    }

    let { sagas }: Props = $props();

    function getCount(state: SagaState): number {
        return sagas.filter((s) => s.state === state).length;
    }
</script>

<div class="mb-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
    {#each Object.values(SagaState) as state (state)}
        {@const info = SAGA_STATES[state]}
        {@const count = getCount(state)}
        {@const IconComponent = info.icon}
        <dl class="card flex items-center justify-between gap-2 p-3 {info.bgColor}">
            <div class="min-w-0">
                <dt class="section-label truncate">{state}</dt>
                <dd class="text-lg font-bold">{count}</dd>
            </div>
            <IconComponent class="size-5 shrink-0 text-fg-muted" />
        </dl>
    {/each}
</div>
