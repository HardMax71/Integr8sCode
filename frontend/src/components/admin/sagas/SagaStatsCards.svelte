<script lang="ts">
    import type { SagaStatusResponse } from '../../../lib/api';
    import { SAGA_STATES, type SagaStateConfig } from '../../../lib/admin/sagas';

    interface Props {
        sagas: SagaStatusResponse[];
    }

    let { sagas }: Props = $props();

    function getCount(state: string): number {
        return sagas.filter(s => s.state === state).length;
    }
</script>

<div class="mb-6 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 sm:gap-3">
    {#each Object.entries(SAGA_STATES) as [state, info]}
        {@const count = getCount(state)}
        {@const IconComponent = info.icon}
        <div class="card hover:shadow-lg transition-all duration-200 {info.bgColor}">
            <div class="p-2 sm:p-3">
                <div class="flex items-center justify-between gap-1">
                    <div class="min-w-0 flex-1">
                        <p class="text-[10px] sm:text-xs text-fg-muted uppercase tracking-wide mb-0.5 truncate">
                            {info.label}
                        </p>
                        <p class="text-base sm:text-lg lg:text-xl font-bold text-fg-default dark:text-dark-fg-default">
                            {count}
                        </p>
                    </div>
                    <IconComponent class="w-4 h-4 sm:w-5 sm:h-5 lg:w-6 lg:h-6 text-fg-muted" />
                </div>
            </div>
        </div>
    {/each}
</div>
