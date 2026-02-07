<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '@mateothegreat/svelte5-router';
    import { authStore } from '$stores/auth.svelte';
    import { AuthInitializer } from '$lib/auth-init';
    import Spinner from '$components/Spinner.svelte';
    import type { Snippet } from 'svelte';

    let {
        redirectTo = '/login',
        message = 'Please log in to access this page',
        children
    }: {
        redirectTo?: string;
        message?: string;
        children?: Snippet;
    } = $props();

    let authReady = $state(false);
    let authorized = $state(false);

    onMount(async () => {
        // Wait for auth initialization
        await AuthInitializer.waitForInit();
        authReady = true;

        // Check if user is authenticated
        authorized = authStore.isAuthenticated ?? false;

        if (!authorized) {
            // Save current path for redirect after login
            const currentPath = window.location.pathname + window.location.search + window.location.hash;
            if (currentPath !== '/login' && currentPath !== '/register') {
                sessionStorage.setItem('redirectAfterLogin', currentPath);
            }

            // Save message for login page
            if (message) {
                sessionStorage.setItem('authMessage', message);
            }

            // Redirect to login
            goto(redirectTo);
        }
    });

    // React to auth revocation after initial load
    $effect(() => {
        if (authReady && authorized && !authStore.isAuthenticated) {
            authorized = false;
            goto(redirectTo);
        }
    });
</script>

{#if !authReady}
    <div class="flex items-center justify-center min-h-screen">
        <Spinner size="large" />
    </div>
{:else if authorized}
    {@render children?.()}
{:else}
    <!-- Show nothing while redirecting -->
    <div class="flex items-center justify-center min-h-screen">
        <Spinner size="large" />
    </div>
{/if}
