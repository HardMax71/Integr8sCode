<script lang="ts">
    import { route, goto } from '@mateothegreat/svelte5-router';
    import { onMount } from 'svelte';
    import { addToast } from '../../stores/toastStore';
    import { isAuthenticated, username, userRole, verifyAuth } from '../../stores/auth';
    import { get } from 'svelte/store';
    import Spinner from '../../components/Spinner.svelte';
    import type { Snippet } from 'svelte';

    let { path = '', children }: { path?: string; children?: Snippet } = $props();

    let user = $state<{ username: string; role: string } | null>(null);
    let loading = $state(true);


    const menuItems = [
        { href: '/admin/events', label: 'Event Browser' },
        { href: '/admin/sagas', label: 'Sagas' },
        { href: '/admin/users', label: 'Users' },
        { href: '/admin/settings', label: 'Settings' },
    ];

    onMount(async () => {
        // First verify authentication with the backend
        try {
            loading = true;

            // Verify auth with backend - this will update the stores
            const authValid = await verifyAuth();

            // Now check the stores after verification
            const isAuth = get(isAuthenticated);
            const currentUsername = get(username);
            const currentRole = get(userRole);

            if (!authValid || !isAuth || !currentUsername) {
                // Save current path for redirect after login
                const currentPath = window.location.pathname + window.location.search + window.location.hash;
                sessionStorage.setItem('redirectAfterLogin', currentPath);

                addToast('Authentication required', 'error');
                goto('/login');
                return;
            }

            // Check for admin role
            if (currentRole !== 'admin') {
                addToast('Admin access required', 'error');
                goto('/');
                return;
            }

            user = { username: currentUsername, role: currentRole };
        } catch (err) {
            console.error('Admin auth check failed:', err);
            // Save current path for redirect after login
            const currentPath = window.location.pathname + window.location.search + window.location.hash;
            sessionStorage.setItem('redirectAfterLogin', currentPath);

            addToast('Authentication required', 'error');
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
                    <svg class="w-6 h-6 text-primary dark:text-primary-light" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                    </svg>
                    <h2 class="text-xl font-bold text-fg-default dark:text-dark-fg-default">Admin Panel</h2>
                </div>

                <nav class="space-y-2">
                    {#each menuItems as item}
                        <a
                            href={item.href}
                            use:route
                            class="flex items-center gap-3 px-4 py-2 rounded-lg transition-colors cursor-pointer"
                            class:bg-primary={path === item.href}
                            class:text-white={path === item.href}
                            class:hover:bg-neutral-200={path !== item.href}
                            class:dark:hover:bg-neutral-700={path !== item.href}
                            class:text-fg-default={path !== item.href}
                            class:dark:text-dark-fg-default={path !== item.href}
                        >
                            <span>{item.label}</span>
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
