<script lang="ts">
    import { fly } from 'svelte/transition';
    import { ChevronDown, ChevronRight } from '@lucide/svelte';
    import type { LanguageInfo } from '../../lib/api';

    interface Props {
        runtimes: Record<string, LanguageInfo>;
        lang: string;
        version: string;
        onselect: (lang: string, version: string) => void;
    }

    let { runtimes, lang, version, onselect }: Props = $props();

    let showOptions = $state(false);
    let hoveredLang = $state<string | null>(null);

    const available = $derived(Object.keys(runtimes).length > 0);
</script>

<div class="relative">
    <button onclick={() => showOptions = !showOptions}
            disabled={!available}
            class="btn btn-secondary-outline btn-sm w-36 flex items-center justify-between text-left"
            class:opacity-50={!available}
            class:cursor-not-allowed={!available}>
        <span class="capitalize truncate">{available ? `${lang} ${version}` : "Unavailable"}</span>
        <span class="ml-2 shrink-0 text-fg-muted dark:text-dark-fg-muted transform transition-transform" class:-rotate-180={showOptions}>
            <ChevronDown class="w-5 h-5" />
        </span>
    </button>

    {#if showOptions && available}
        <div transition:fly={{ y: -5, duration: 150 }}
             class="absolute bottom-full mb-2 w-36 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 z-30">
            <ul class="py-1" onmouseleave={() => hoveredLang = null}>
                {#each Object.entries(runtimes) as [l, info] (l)}
                    <li class="relative" onmouseenter={() => hoveredLang = l}>
                        <div class="flex justify-between items-center w-full px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                            <span class="capitalize font-medium">{l}</span>
                            <ChevronRight class="w-4 h-4 text-fg-muted dark:text-dark-fg-muted" />
                        </div>

                        {#if hoveredLang === l && info.versions.length > 0}
                            <div class="absolute left-full top-0 -mt-1 ml-1 w-20 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-lg ring-1 ring-black/5 dark:ring-white/10 z-40"
                                 transition:fly={{ x: 5, duration: 100 }}>
                                <ul class="py-1 max-h-60 overflow-y-auto custom-scrollbar">
                                    {#each info.versions as v (v)}
                                        <li>
                                            <button onclick={() => { onselect(l, v); showOptions = false; hoveredLang = null; }}
                                                    class="w-full text-left px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-700/60 transition-colors duration-100"
                                                    class:text-primary={l === lang && v === version}
                                                    class:dark:text-primary-light={l === lang && v === version}
                                                    class:font-semibold={l === lang && v === version}
                                                    class:text-fg-default={l !== lang || v !== version}
                                                    class:dark:text-dark-fg-default={l !== lang || v !== version}>
                                                {v}
                                            </button>
                                        </li>
                                    {/each}
                                </ul>
                            </div>
                        {/if}
                    </li>
                {/each}
            </ul>
        </div>
    {/if}
</div>
