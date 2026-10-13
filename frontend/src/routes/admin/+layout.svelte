<script lang="ts">
    import { resolve } from '$app/paths';
    import { page } from '$app/state';
    import { ShieldCheck } from '@lucide/svelte';
    import { ADMIN_ROUTES } from '#lib/admin/constants.ts';
    import type { LayoutProps } from './$types';

    let { data, children }: LayoutProps = $props();

    const path = $derived(page.url.pathname);

    let nav = $state<HTMLElement>();

    // On a narrow screen the links scroll sideways, so bring the current one into view
    $effect(() => {
        void path;
        nav?.querySelector('[aria-current="page"]')?.scrollIntoView?.({ block: 'nearest', inline: 'center' });
    });
</script>

<div class="lg:flex">
    <!-- A fixed sidebar from lg up; above the content as a scrolling row of links below it -->
    <aside
        class="bg-bg-sidebar dark:bg-dark-bg-sidebar border-b border-border-default dark:border-dark-border-default lg:border-b-0 lg:shadow-lg lg:fixed lg:left-0 lg:top-16 lg:bottom-0 lg:w-64 lg:overflow-y-auto lg:z-10"
    >
        <div class="p-3 lg:p-4">
            <div class="hidden lg:flex items-center gap-2 mb-8">
                <ShieldCheck class="w-6 h-6 text-primary dark:text-primary-light" />
                <h2 class="text-xl font-bold text-fg-default dark:text-dark-fg-default">Admin Panel</h2>
            </div>

            <nav bind:this={nav} aria-label="Admin" class="flex gap-2 overflow-x-auto lg:block lg:space-y-2">
                {#each ADMIN_ROUTES as navItem (navItem.path)}
                    {@const href = resolve(navItem.path)}
                    <a
                        {href}
                        aria-current={path === href ? 'page' : undefined}
                        class="flex shrink-0 items-center gap-3 whitespace-nowrap px-4 py-2 rounded-lg transition-colors cursor-pointer"
                        class:bg-primary={path === href}
                        class:text-white={path === href}
                        class:hover:bg-neutral-200={path !== href}
                        class:dark:hover:bg-neutral-700={path !== href}
                        class:text-fg-default={path !== href}
                        class:dark:text-dark-fg-default={path !== href}
                    >
                        <span>{navItem.sidebarLabel}</span>
                    </a>
                {/each}
            </nav>

            <div
                class="hidden lg:block mt-8 p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg border border-border-default dark:border-dark-border-default"
            >
                <p class="text-sm text-fg-muted dark:text-dark-fg-muted">Logged in as:</p>
                <p class="font-semibold truncate text-fg-default dark:text-dark-fg-default">
                    {data.user.username}
                </p>
            </div>
        </div>
    </aside>

    <div class="flex-1 lg:ml-64 pb-16">
        {@render children()}
    </div>
</div>
