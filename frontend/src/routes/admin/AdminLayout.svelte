<script lang="ts">
    import { route, goto } from '@mateothegreat/svelte5-router';
    import { onMount } from 'svelte';
    import { toast } from 'svelte-sonner';
    import { authStore } from '$stores/auth.svelte';
    import Spinner from '$components/Spinner.svelte';
    import type { Snippet } from 'svelte';
    import { ShieldCheck } from '@lucide/svelte';
    import { ADMIN_ROUTES } from '$lib/admin/constants';

    let { path = '', children }: { path?: string; children?: Snippet } = $props();

    let user = $state<{ username: string; role: string } | null>(null);
    let loading = $state(true);

    onMount(async () => {
        // First verify authentication with the backend
        try {
            loading = true;

            // Verify auth with backend - this will update the stores
            const authValid = await authStore.verifyAuth();

            // Now check the stores after verification
            if (!authValid || !authStore.isAuthenticated || !authStore.username) {
                // Save current path for redirect after login
                const currentPath = window.location.pathname + window.location.search + window.location.hash;
                sessionStorage.setItem('redirectAfterLogin', currentPath);

                toast.error('Authentication required');
                goto('/login');
                return;
            }

            // Check for admin role
            if (authStore.userRole !== 'admin') {
                toast.error('Admin access required');
                goto('/');
                return;
            }

            user = { username: authStore.username, role: authStore.userRole };
        } catch (err) {
            console.error('Admin auth check failed:', err);
            // Save current path for redirect after login
            const currentPath = window.location.pathname + window.location.search + window.location.hash;
            sessionStorage.setItem('redirectAfterLogin', currentPath);

            toast.error('Authentication required');
            goto('/login');
        } finally {
            loading = false;
        }
    });
</script>

{#if loading}
    <div class="flex items-center justify-center min-h-screen">
        <div class="text-center">
            <Spinner size="xlarge" className="mx-auto mb-4" />
            <p class="text-fg-muted dark:text-dark-fg-muted">Verifying authentication...</p>
        </div>
    </div>
{:else}
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
                            use:route
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

                {#if user}
                    <div class="mt-8 p-4 bg-bg-alt dark:bg-dark-bg-alt rounded-lg border border-border-default dark:border-dark-border-default">
                        <p class="text-sm text-fg-muted dark:text-dark-fg-muted">Logged in as:</p>
                        <p class="font-semibold truncate text-fg-default dark:text-dark-fg-default">{user.username}</p>
                    </div>
                {/if}
            </div>
    </div>

        <!-- Main content -->
        <div class="flex-1 ml-64 pb-16">
            {@render children?.()}
        </div>
    </div>
{/if}
