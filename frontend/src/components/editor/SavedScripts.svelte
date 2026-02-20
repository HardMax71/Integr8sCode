<script lang="ts">
    import { slide } from 'svelte/transition';
    import { List, Trash2 } from '@lucide/svelte';
    import { type SavedScriptResponse } from '$lib/api';

    interface Props {
        scripts: SavedScriptResponse[];
        onload: (script: SavedScriptResponse) => void;
        ondelete: (id: string) => void;
        onrefresh: () => void;
    }

    let { scripts, onload, ondelete, onrefresh }: Props = $props();

    let show = $state(false);

    function toggle() {
        show = !show;
        if (show) onrefresh();
    }
</script>

<div class="space-y-3">
    <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Saved Scripts</h4>
    <div>
        <button class="btn btn-secondary-outline btn-sm w-full inline-flex items-center justify-center space-x-1.5"
                onclick={toggle}
                aria-expanded={show}
                title={show ? "Hide Saved Scripts" : "Show Saved Scripts"}>
            <List class="w-4 h-4" />
            <span>{show ? "Hide" : "Show"} Saved Scripts</span>
        </button>
    </div>
    {#if show}
        <div class="mt-2" transition:slide={{ duration: 200 }}>
            {#if scripts.length > 0}
                <div class="saved-scripts-container border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default shadow-inner">
                    <ul class="divide-y divide-border-default dark:divide-dark-border-default">
                        {#each scripts as item (item.script_id)}
                            <li class="flex items-center justify-between hover:bg-neutral-100 dark:hover:bg-neutral-700/50 text-sm group transition-colors duration-100">
                                <button class="flex-grow text-left px-3 py-2 text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light font-medium min-w-0"
                                        onclick={() => onload(item)}
                                        title={`Load ${item.name} (${item.lang} ${item.lang_version})`}>
                                    <div class="flex flex-col min-w-0">
                                        <span class="truncate">{item.name}</span>
                                        <span class="text-xs text-fg-muted dark:text-dark-fg-muted font-normal capitalize">
                                            {item.lang} {item.lang_version}
                                        </span>
                                    </div>
                                </button>
                                <button class="p-2 text-neutral-400 dark:text-neutral-500 hover:text-red-500 dark:hover:text-red-400 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity duration-150 mr-1"
                                        onclick={(e) => { e.stopPropagation(); ondelete(item.script_id); }}
                                        title={`Delete ${item.name}`}>
                                    <span class="sr-only">Delete</span>
                                    <Trash2 class="w-4 h-4" />
                                </button>
                            </li>
                        {/each}
                    </ul>
                </div>
            {:else}
                <p class="p-4 text-xs text-fg-muted dark:text-dark-fg-muted italic text-center border border-border-default dark:border-dark-border-default rounded-lg">
                    No saved scripts yet.
                </p>
            {/if}
        </div>
    {/if}
</div>
