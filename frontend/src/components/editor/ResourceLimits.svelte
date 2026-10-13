<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { Popover } from 'bits-ui';
    import { MessageSquare, ChevronDown, Cpu, MemoryStick, Clock } from '@lucide/svelte';
    import { getK8sResourceLimitsApiV1K8sLimitsGetOptions } from '#lib/api/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import { draft, pickRuntime } from '#lib/editor/index.ts';

    const limits = createQuery(() => getK8sResourceLimitsApiV1K8sLimitsGetOptions());
    const lang = $derived(pickRuntime(draft.current, limits.data?.supported_runtimes ?? {}).lang);
    const effective = $derived(limits.data?.language_limits[lang]);
</script>

{#snippet limit(Icon: typeof Cpu, key: string, value: string)}
    <div class="flex items-center justify-between">
        <dt class="inline-flex items-center gap-2 text-fg-muted"><Icon class="size-4" />{fieldTitle(key)}</dt>
        <dd class="font-semibold tabular-nums">{value}</dd>
    </div>
{/snippet}

{#if effective}
    <Popover.Root>
        <Popover.Trigger class="btn btn-secondary-outline btn-sm gap-1.5 w-full sm:w-auto shrink-0 group">
            <MessageSquare class="size-4" />
            <span>Resource Limits</span>
            <ChevronDown class="size-4 transition-transform group-data-[state=open]:-rotate-180" />
        </Popover.Trigger>
        <Popover.Portal>
            <Popover.Content align="end" sideOffset={8} class="floating-panel w-64 sm:w-72 p-5">
                <dl class="space-y-4 text-sm">
                    {@render limit(Cpu, 'cpu_limit', effective.cpu_limit)}
                    {@render limit(MemoryStick, 'memory_limit', effective.memory_limit)}
                    {@render limit(Clock, 'execution_timeout', `${effective.execution_timeout}s`)}
                </dl>
            </Popover.Content>
        </Popover.Portal>
    </Popover.Root>
{/if}
