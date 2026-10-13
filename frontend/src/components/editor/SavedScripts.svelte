<script lang="ts">
    import { resolve } from '$app/paths';
    import { slide } from 'svelte/transition';
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { List, Trash } from '@lucide/svelte';
    import { toast } from 'svelte-sonner';
    import {
        deleteSavedScriptApiV1ScriptsScriptIdDeleteMutation,
        listSavedScriptsApiV1ScriptsGetOptions,
        listSavedScriptsApiV1ScriptsGetQueryKey,
        type SavedScriptResponse,
    } from '#lib/api/index.ts';
    import { authStore } from '#stores/auth.svelte.ts';
    import { draft, executionContext, newScript, openScript } from '#lib/editor/index.ts';

    const queryClient = useQueryClient();
    const execution = executionContext.get();
    const signedIn = $derived(authStore.session.status === 'signed-in');
    const list = createQuery(() => ({ ...listSavedScriptsApiV1ScriptsGetOptions(), enabled: signedIn }));
    const scripts = $derived(list.data?.scripts ?? []);

    const remove = createMutation(() => ({
        ...deleteSavedScriptApiV1ScriptsScriptIdDeleteMutation(),
        onSuccess: (_data, { path }) => {
            toast.success('Script deleted successfully.');
            if (draft.current.script_id === path.script_id) newScript();
            return queryClient.invalidateQueries({ queryKey: listSavedScriptsApiV1ScriptsGetQueryKey() });
        },
    }));

    let show = $state(false);

    function toggle(): void {
        show = !show;
        if (show) void list.refetch();
    }

    function open(saved: SavedScriptResponse): void {
        openScript(saved);
        execution.reset();
        toast.info(`Loaded script: ${saved.name}`);
    }

    function confirmDelete(saved: SavedScriptResponse): void {
        if (!confirm(`Are you sure you want to delete "${saved.name}"?`)) return;
        remove.mutate({ path: { script_id: saved.script_id } });
    }
</script>

{#if !signedIn}
    <div class="flex flex-col items-center justify-center h-full text-center">
        <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-2">
            Saved Scripts
        </h4>
        <p class="text-xs text-fg-muted dark:text-dark-fg-muted">
            <a href={resolve('/login')} class="link">Log in</a> to save and manage your scripts.
        </p>
    </div>
{:else}
    <div class="space-y-3">
        <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">
            Saved Scripts
        </h4>
        <div>
            <button
                type="button"
                class="btn btn-secondary-outline btn-sm w-full inline-flex items-center justify-center space-x-1.5"
                onclick={toggle}
                aria-expanded={show}
                title={show ? 'Hide Saved Scripts' : 'Show Saved Scripts'}
            >
                <List class="w-4 h-4" />
                <span>{show ? 'Hide' : 'Show'} Saved Scripts</span>
            </button>
        </div>
        {#if show}
            <div class="mt-2" transition:slide={{ duration: 200 }}>
                {#if scripts.length > 0}
                    <div
                        class="saved-scripts-container border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default shadow-inner"
                    >
                        <ul class="divide-y divide-border-default dark:divide-dark-border-default">
                            {#each scripts as item (item.script_id)}
                                <li
                                    class="flex items-center justify-between hover:bg-neutral-100 dark:hover:bg-neutral-700/50 text-sm group transition-colors duration-100"
                                >
                                    <button
                                        type="button"
                                        class="flex-grow text-left px-3 py-2 text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light font-medium min-w-0"
                                        onclick={() => open(item)}
                                        title={`Load ${item.name} (${item.lang} ${item.lang_version})`}
                                    >
                                        <div class="flex flex-col min-w-0">
                                            <span class="truncate">{item.name}</span>
                                            <span
                                                class="text-xs text-fg-muted dark:text-dark-fg-muted font-normal capitalize"
                                            >
                                                {item.lang}
                                                {item.lang_version}
                                            </span>
                                        </div>
                                    </button>
                                    <button
                                        type="button"
                                        class="p-2 text-neutral-400 dark:text-neutral-500 hover:text-red-500 dark:hover:text-red-400 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity duration-150 mr-1"
                                        onclick={() => confirmDelete(item)}
                                        aria-label={`Delete ${item.name}`}
                                        title={`Delete ${item.name}`}
                                    >
                                        <Trash class="w-4 h-4" />
                                    </button>
                                </li>
                            {/each}
                        </ul>
                    </div>
                {:else}
                    <p
                        class="p-4 text-xs text-fg-muted dark:text-dark-fg-muted italic text-center border border-border-default dark:border-dark-border-default rounded-lg"
                    >
                        No saved scripts yet.
                    </p>
                {/if}
            </div>
        {/if}
    </div>
{/if}
