<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { Check, ChevronDown, ChevronRight } from '@lucide/svelte';
    import { DropdownMenu } from 'bits-ui';
    import { getK8sResourceLimitsApiV1K8sLimitsGetOptions } from '#lib/api/index.ts';
    import { draft, pickRuntime } from '#lib/editor/index.ts';

    const limits = createQuery(() => getK8sResourceLimitsApiV1K8sLimitsGetOptions());
    const runtimes = $derived(limits.data?.supported_runtimes ?? {});
    const available = $derived(Object.keys(runtimes).length > 0);

    const current = $derived(pickRuntime(draft.current, runtimes));

    function select(lang: string, version: string): void {
        draft.current.lang = lang;
        draft.current.lang_version = version;
    }
</script>

<DropdownMenu.Root>
    <DropdownMenu.Trigger
        disabled={!available}
        aria-label="Select language and version"
        class="btn btn-secondary-outline btn-sm w-36 flex items-center justify-between text-left disabled:opacity-50 disabled:cursor-not-allowed group"
    >
        <span class="capitalize truncate">{available ? `${current.lang} ${current.lang_version}` : 'Unavailable'}</span>
        <ChevronDown
            class="ml-2 w-5 h-5 shrink-0 text-fg-muted dark:text-dark-fg-muted transition-transform group-data-[state=open]:-rotate-180"
        />
    </DropdownMenu.Trigger>
    <DropdownMenu.Portal>
        <DropdownMenu.Content
            side="top"
            align="start"
            sideOffset={8}
            class="floating-panel w-36"
            aria-label="Select language and version"
        >
            {#each Object.entries(runtimes) as [l, info] (l)}
                <DropdownMenu.Sub>
                    <DropdownMenu.SubTrigger class="floating-item justify-between capitalize font-medium">
                        {l}
                        <ChevronRight class="w-4 h-4 text-fg-muted dark:text-dark-fg-muted" />
                    </DropdownMenu.SubTrigger>
                    <DropdownMenu.Portal>
                        <DropdownMenu.SubContent
                            sideOffset={4}
                            class="floating-panel min-w-24 max-h-60 overflow-y-auto"
                            aria-label="{l} versions"
                        >
                            <DropdownMenu.RadioGroup
                                value={l === current.lang ? current.lang_version : ''}
                                onValueChange={(v) => select(l, v)}
                            >
                                {#each info.versions as v (v)}
                                    <DropdownMenu.RadioItem value={v} class="floating-item justify-between">
                                        {#snippet children({ checked })}
                                            <span class:font-semibold={checked}>{v}</span>
                                            {#if checked}<Check class="w-4 h-4 text-primary" />{/if}
                                        {/snippet}
                                    </DropdownMenu.RadioItem>
                                {/each}
                            </DropdownMenu.RadioGroup>
                        </DropdownMenu.SubContent>
                    </DropdownMenu.Portal>
                </DropdownMenu.Sub>
            {/each}
        </DropdownMenu.Content>
    </DropdownMenu.Portal>
</DropdownMenu.Root>
