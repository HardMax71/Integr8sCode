<script>
    import { onMount } from 'svelte';
    import { navigate } from 'svelte-routing';
    import { isAuthenticated } from '../stores/auth';
    import { AuthInitializer } from '../lib/auth-init';
    import Spinner from './Spinner.svelte';
    
    export let redirectTo = '/login';
    export let message = 'Please log in to access this page';
    
    let authReady = false;
    let authorized = false;
    
    onMount(async () => {
        // Wait for auth initialization
        await AuthInitializer.waitForInit();
        authReady = true;
        
        // Check if user is authenticated
        authorized = $isAuthenticated;
        
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
            navigate(redirectTo);
        }
    });
    
    // React to auth changes
    $: if (authReady && !$isAuthenticated) {
        authorized = false;
        navigate(redirectTo);
    }
</script>

{#if !authReady}
    <div class="flex items-center justify-center min-h-screen">
        <Spinner size="large" />
    </div>
{:else if authorized}
    <slot />
{:else}
    <!-- Show nothing while redirecting -->
    <div class="flex items-center justify-center min-h-screen">
        <Spinner size="large" />
    </div>
{/if}