<script lang="ts">
    import { fly } from 'svelte/transition';
    import { ChevronDown, ChevronRight } from '@lucide/svelte';
    import type { LanguageInfo } from '$lib/api';

    interface Props {
        runtimes: Record<string, LanguageInfo>;
        lang: string;
        version: string;
        onselect: (lang: string, version: string) => void;
    }

    let { runtimes, lang, version, onselect }: Props = $props();

    let showOptions = $state(false);
    let hoveredLang = $state<string | null>(null);
    let focusedLangIndex = $state(-1);
    let focusedVersionIndex = $state(-1);

    const available = $derived(Object.keys(runtimes).length > 0);
    const langKeys = $derived(Object.keys(runtimes));

    function closeMenu() {
        showOptions = false;
        hoveredLang = null;
        focusedLangIndex = -1;
        focusedVersionIndex = -1;
    }

    function selectVersion(l: string, v: string) {
        onselect(l, v);
        closeMenu();
    }

    function handleTriggerKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape' && showOptions) {
            e.preventDefault();
            closeMenu();
        } else if ((e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') && !showOptions && available) {
            e.preventDefault();
            showOptions = true;
            focusedLangIndex = 0;
        }
    }

    function handleMenuKeydown(e: KeyboardEvent) {
        const inSubmenu = hoveredLang !== null && focusedVersionIndex >= 0;
        const currentVersions = hoveredLang ? runtimes[hoveredLang]?.versions ?? [] : [];

        if (e.key === 'Escape') {
            e.preventDefault();
            if (inSubmenu) {
                hoveredLang = null;
                focusedVersionIndex = -1;
            } else {
                closeMenu();
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (inSubmenu) {
                focusedVersionIndex = Math.min(focusedVersionIndex + 1, currentVersions.length - 1);
            } else {
                focusedLangIndex = Math.min(focusedLangIndex + 1, langKeys.length - 1);
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (inSubmenu) {
                focusedVersionIndex = Math.max(focusedVersionIndex - 1, 0);
            } else {
                focusedLangIndex = Math.max(focusedLangIndex - 1, 0);
            }
        } else if (e.key === 'ArrowRight' || e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (inSubmenu && (e.key === 'Enter' || e.key === ' ')) {
                selectVersion(hoveredLang!, currentVersions[focusedVersionIndex]!);
            } else if (!inSubmenu && focusedLangIndex >= 0) {
                hoveredLang = langKeys[focusedLangIndex] ?? null;
                focusedVersionIndex = 0;
            }
        } else if (e.key === 'ArrowLeft' && inSubmenu) {
            e.preventDefault();
            hoveredLang = null;
            focusedVersionIndex = -1;
        }
    }
</script>

<div class="relative">
    <button type="button" onclick={() => { showOptions = !showOptions; if (showOptions) focusedLangIndex = 0; }}
            onkeydown={handleTriggerKeydown}
            disabled={!available}
            aria-haspopup="menu"
            aria-expanded={showOptions}
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
             role="menu"
             tabindex="-1"
             aria-label="Select language and version"
             onkeydown={handleMenuKeydown}
             class="absolute bottom-full mb-2 w-36 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 z-30">
            <ul class="py-1" onmouseleave={() => { hoveredLang = null; focusedVersionIndex = -1; }}>
                {#each Object.entries(runtimes) as [l, info], i (l)}
                    <li class="relative" role="none"
                        onmouseenter={() => { hoveredLang = l; focusedLangIndex = i; focusedVersionIndex = -1; }}>
                        <button type="button"
                                role="menuitem"
                                aria-haspopup="menu"
                                aria-expanded={hoveredLang === l}
                                tabindex={focusedLangIndex === i ? 0 : -1}
                                onfocus={() => { focusedLangIndex = i; }}
                                class="flex justify-between items-center w-full px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default text-left"
                                class:bg-neutral-100={focusedLangIndex === i}
                                class:dark:bg-neutral-700={focusedLangIndex === i}>
                            <span class="capitalize font-medium">{l}</span>
                            <ChevronRight class="w-4 h-4 text-fg-muted dark:text-dark-fg-muted" />
                        </button>

                        {#if hoveredLang === l && info.versions.length > 0}
                            <div class="absolute left-full top-0 -mt-1 ml-1 w-20 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-lg ring-1 ring-black/5 dark:ring-white/10 z-40"
                                 role="menu"
                                 aria-label="{l} versions"
                                 transition:fly={{ x: 5, duration: 100 }}>
                                <ul class="py-1 max-h-60 overflow-y-auto custom-scrollbar">
                                    {#each info.versions as v, vi (v)}
                                        <li role="none">
                                            <button type="button" onclick={() => selectVersion(l, v)}
                                                    role="menuitemradio"
                                                    aria-checked={l === lang && v === version}
                                                    tabindex={focusedVersionIndex === vi ? 0 : -1}
                                                    class="w-full text-left px-3 py-1.5 text-sm transition-colors duration-100"
                                                    class:bg-neutral-100={focusedVersionIndex === vi}
                                                    class:dark:bg-neutral-700={focusedVersionIndex === vi}
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
