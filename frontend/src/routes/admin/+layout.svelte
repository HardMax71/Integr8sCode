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
        class="bg-sidebar border-b lg:border-b-0 lg:shadow-lg lg:fixed lg:left-0 lg:top-16 lg:bottom-0 lg:w-64 lg:overflow-y-auto lg:z-10"
    >
        <div class="p-3 lg:p-4">
            <div class="hidden lg:flex items-center gap-2 mb-8">
                <ShieldCheck class="size-6 text-accent" />
                <h2 class="font-bold">Admin Panel</h2>
            </div>

            <nav bind:this={nav} aria-label="Admin" class="flex gap-2 overflow-x-auto lg:flex-col">
                {#each ADMIN_ROUTES as navItem (navItem.path)}
                    {@const href = resolve(navItem.path)}
                    <a
                        {href}
                        aria-current={path === href ? 'page' : undefined}
                        class={[
                            'flex shrink-0 items-center gap-3 whitespace-nowrap px-4 py-2 rounded-lg transition-colors',
                            path === href ? 'bg-primary text-white' : 'hover:bg-fg/10',
                        ]}
                    >
                        <span>{navItem.sidebarLabel}</span>
                    </a>
                {/each}
            </nav>

            <div class="hidden lg:block mt-8 p-4 bg-surface rounded-lg border">
                <p class="text-sm text-fg-muted">Logged in as:</p>
                <p class="font-semibold truncate">
                    {data.user.username}
                </p>
            </div>
        </div>
    </aside>

    <div class="flex-1 lg:ml-64 pb-16">
        {@render children()}
    </div>
</div>
