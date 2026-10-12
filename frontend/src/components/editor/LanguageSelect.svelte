<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { Check, ChevronDown, ChevronRight } from '@lucide/svelte';
    import { DropdownMenu } from 'bits-ui';
    import { toast } from 'svelte-sonner';
    import { getK8sResourceLimitsApiV1K8sLimitsGetOptions } from '#lib/api/index.ts';
    import { draft } from '#lib/editor/index.ts';

    const limits = createQuery(() => getK8sResourceLimitsApiV1K8sLimitsGetOptions());
    const runtimes = $derived(limits.data?.supported_runtimes ?? {});
    const available = $derived(Object.keys(runtimes).length > 0);

    // A stored or loaded language or version the API no longer offers falls back to one it does; .pre, so the menu never shows the old one
    $effect.pre(() => {
        const offered = limits.data?.supported_runtimes;
        const { lang, lang_version } = draft.current;
        if (!offered) return;
        const nextLang = lang in offered ? lang : Object.keys(offered)[0];
        const versions = nextLang ? (offered[nextLang]?.versions ?? []) : [];
        if (!nextLang || (nextLang === lang && versions.includes(lang_version))) return;
        const nextVersion = versions[0] ?? '';
        if (nextLang === lang) {
            toast.info(`Version ${lang_version} of ${lang} is no longer available, switched to ${nextVersion}.`);
        }
        draft.current.lang = nextLang;
        draft.current.lang_version = nextVersion;
    });

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
        <span class="capitalize truncate"
            >{available ? `${draft.current.lang} ${draft.current.lang_version}` : 'Unavailable'}</span
        >
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
                                value={l === draft.current.lang ? draft.current.lang_version : ''}
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
