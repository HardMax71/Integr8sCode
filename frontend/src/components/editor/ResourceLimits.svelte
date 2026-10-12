<script lang="ts">
    import { fly } from 'svelte/transition';
    import { MessageSquare, ChevronUp, ChevronDown, Cpu, MemoryStick, Clock } from '@lucide/svelte';
    import type { ResourceLimits as ResourceLimitsType } from '#lib/api/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';

    interface Props {
        limits: ResourceLimitsType | null;
        lang: string;
    }
    let { limits, lang }: Props = $props();

    let show = $state(false);
    let effective = $derived(limits?.language_limits[lang] ?? null);
</script>

{#if effective}
    <div class="relative shrink-0">
        <button
            type="button"
            class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5 w-full sm:w-auto justify-center"
            onclick={() => (show = !show)}
            aria-expanded={show}
        >
            <MessageSquare class="w-4 h-4" />
            <span>Resource Limits</span>
            {#if show}<ChevronUp class="w-4 h-4" />{:else}<ChevronDown class="w-4 h-4" />{/if}
        </button>
        {#if show}
            <div
                class="absolute right-0 top-full mt-2 w-64 sm:w-72 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 p-5 z-30 border border-border-default dark:border-dark-border-default"
                transition:fly={{ y: 10, duration: 200 }}
            >
                <div class="space-y-4">
                    <div class="flex items-center justify-between text-sm">
                        <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center">
                            <span class="mr-2"><Cpu class="w-4 h-4" /></span>{fieldTitle('cpu_limit')}
                        </span>
                        <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums"
                            >{effective.cpu_limit}</span
                        >
                    </div>
                    <div class="flex items-center justify-between text-sm">
                        <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center">
                            <span class="mr-2"><MemoryStick class="w-4 h-4" /></span>{fieldTitle('memory_limit')}
                        </span>
                        <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums"
                            >{effective.memory_limit}</span
                        >
                    </div>
                    <div class="flex items-center justify-between text-sm">
                        <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center">
                            <span class="mr-2"><Clock class="w-4 h-4" /></span>{fieldTitle('execution_timeout')}
                        </span>
                        <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums"
                            >{effective.execution_timeout}s</span
                        >
                    </div>
                </div>
            </div>
        {/if}
    </div>
{/if}
