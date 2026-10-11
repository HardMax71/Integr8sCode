<script lang="ts">
    import type { Snippet } from 'svelte';
    import { page } from '$app/state';
    import { ShieldCheck } from '@lucide/svelte';
    import { authStore } from '#stores/auth.svelte.ts';
    import { ADMIN_ROUTES } from '#lib/admin/constants.ts';

    let { children }: { children: Snippet } = $props();

    const path = $derived(page.url.pathname);
</script>

<div class="flex">
    <!-- Sidebar -->
    <div class="w-64 bg-bg-sidebar dark:bg-dark-bg-sidebar shadow-lg fixed left-0 top-16 bottom-0 overflow-y-auto z-10">
        <div class="p-4">
            <div class="flex items-center gap-2 mb-8">
                <ShieldCheck class="w-6 h-6 text-primary dark:text-primary-light" />
                <h2 class="text-xl font-bold text-fg-default dark:text-dark-fg-default">Admin Panel</h2>
            </div>

            <nav class="space-y-2">
                {#each ADMIN_ROUTES as navItem}
                    <a
                        href={navItem.path}
                        class="flex items-center gap-3 px-4 py-2 rounded-lg transition-colors cursor-pointer"
                        class:bg-primary={path === navItem.path}
                        class:text-white={path === navItem.path}
                        class:hover:bg-neutral-200={path !== navItem.path}
                        class:dark:hover:bg-neutral-700={path !== navItem.path}
                        class:text-fg-default={path !== navItem.path}
                        class:dark:text-dark-fg-default={path !== navItem.path}
                    >
                        <span>{navItem.sidebarLabel}</span>
                    </a>
                {/each}
            </nav>

            {#if authStore.username}
                <div
                    class="mt-8 p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg border border-border-default dark:border-dark-border-default"
                >
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted">Logged in as:</p>
                    <p class="font-semibold truncate text-fg-default dark:text-dark-fg-default">{authStore.username}</p>
                </div>
            {/if}
        </div>
    </div>

    <!-- Main content -->
    <div class="flex-1 ml-64 pb-16">
        {@render children()}
    </div>
</div>
