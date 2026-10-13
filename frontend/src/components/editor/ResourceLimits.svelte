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

{#if effective}
    <Popover.Root>
        <Popover.Trigger
            class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5 w-full sm:w-auto justify-center shrink-0 group"
        >
            <MessageSquare class="w-4 h-4" />
            <span>Resource Limits</span>
            <ChevronDown class="w-4 h-4 transition-transform group-data-[state=open]:-rotate-180" />
        </Popover.Trigger>
        <Popover.Portal>
            <Popover.Content align="end" sideOffset={8} class="floating-panel w-64 sm:w-72 p-5 space-y-4">
                <div class="flex items-center justify-between text-sm">
                    <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center">
                        <Cpu class="w-4 h-4 mr-2" />{fieldTitle('cpu_limit')}
                    </span>
                    <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums"
                        >{effective.cpu_limit}</span
                    >
                </div>
                <div class="flex items-center justify-between text-sm">
                    <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center">
                        <MemoryStick class="w-4 h-4 mr-2" />{fieldTitle('memory_limit')}
                    </span>
                    <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums"
                        >{effective.memory_limit}</span
                    >
                </div>
                <div class="flex items-center justify-between text-sm">
                    <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center">
                        <Clock class="w-4 h-4 mr-2" />{fieldTitle('execution_timeout')}
                    </span>
                    <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums"
                        >{effective.execution_timeout}s</span
                    >
                </div>
            </Popover.Content>
        </Popover.Portal>
    </Popover.Root>
{/if}
