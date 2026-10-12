<script lang="ts">
    import { Check, ChevronDown, ChevronRight } from '@lucide/svelte';
    import { DropdownMenu } from 'bits-ui';
    import { toast } from 'svelte-sonner';
    import type { ResourceLimits } from '#lib/api/index.ts';

    interface Props {
        runtimes: ResourceLimits['supported_runtimes'];
        lang: string;
        version: string;
        onselect: (lang: string, version: string) => void;
    }

    let { runtimes, lang, version, onselect }: Props = $props();

    const available = $derived(Object.keys(runtimes).length > 0);

    $effect(() => {
        const versions = runtimes[lang]?.versions ?? [];
        const fallback = versions[0];
        if (!fallback || versions.includes(version)) return;
        toast.info(`Version ${version} of ${lang} is no longer available, switched to ${fallback}.`);
        onselect(lang, fallback);
    });
</script>

<DropdownMenu.Root>
    <DropdownMenu.Trigger
        disabled={!available}
        aria-label="Select language and version"
        class="btn btn-secondary-outline btn-sm w-36 flex items-center justify-between text-left disabled:opacity-50 disabled:cursor-not-allowed group"
    >
        <span class="capitalize truncate">{available ? `${lang} ${version}` : 'Unavailable'}</span>
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
                                value={l === lang ? version : ''}
                                onValueChange={(v) => onselect(l, v)}
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
