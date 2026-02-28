<script lang="ts">
    import { onMount } from 'svelte';
    import { Router, goto } from "@mateothegreat/svelte5-router";
    import { Toaster } from 'svelte-sonner';
    import Header from "$components/Header.svelte";
    import Footer from "$components/Footer.svelte";
    import Spinner from "$components/Spinner.svelte";
    import ErrorDisplay from "$components/ErrorDisplay.svelte";
    import { themeStore } from '$stores/theme.svelte';
    import { appError } from '$stores/errorStore.svelte';
    import { authStore } from '$stores/auth.svelte';
    import { logger } from '$lib/logger';

    const log = logger.withTag('App');

    // Page components
    import Home from "$routes/Home.svelte";
    import Login from "$routes/Login.svelte";
    import Register from "$routes/Register.svelte";
    import Privacy from "$routes/Privacy.svelte";
    import Editor from "$routes/Editor.svelte";
    import Settings from "$routes/Settings.svelte";
    import Notifications from "$routes/Notifications.svelte";
    import AdminEvents from "$routes/admin/AdminEvents.svelte";
    import AdminExecutions from "$routes/admin/AdminExecutions.svelte";
    import AdminSagas from "$routes/admin/AdminSagas.svelte";
    import AdminUsers from "$routes/admin/AdminUsers.svelte";
    import AdminSettings from "$routes/admin/AdminSettings.svelte";

    let authInitialized = $state(false);

    // Initialize auth before rendering routes
    onMount(async () => {
        try {
            await authStore.initialize();
            log.info('Authentication initialized');
        } catch (err) {
            log.error('Auth initialization failed:', err);
        } finally {
            authInitialized = true;
        }
    });

    // --8<-- [start:require_auth]
    // Auth hook for protected routes
    const requireAuth = async () => {
        await authStore.waitForInit();
        if (!authStore.isAuthenticated) {
            const currentPath = window.location.pathname + window.location.search;
            if (currentPath !== '/login' && currentPath !== '/register') {
                sessionStorage.setItem('redirectAfterLogin', currentPath);
            }
            goto('/login');
            return false;
        }
        return true;
    };
    // --8<-- [end:require_auth]

    // --8<-- [start:routes]
    // Routes configuration
    const routes = [
        // Public routes
        { path: "/", component: Home },
        { path: "/login", component: Login },
        { path: "/register", component: Register },
        { path: "/privacy", component: Privacy },
        // Protected routes
        { path: "/editor", component: Editor, hooks: { pre: requireAuth } },
        { path: "/settings", component: Settings, hooks: { pre: requireAuth } },
        { path: "/notifications", component: Notifications, hooks: { pre: requireAuth } },
        { path: "/admin/events", component: AdminEvents, hooks: { pre: requireAuth } },
        { path: "/admin/executions", component: AdminExecutions, hooks: { pre: requireAuth } },
        { path: "/admin/sagas", component: AdminSagas, hooks: { pre: requireAuth } },
        { path: "/admin/users", component: AdminUsers, hooks: { pre: requireAuth } },
        { path: "/admin/settings", component: AdminSettings, hooks: { pre: requireAuth } },
        { path: "^/admin$", component: AdminEvents, hooks: { pre: requireAuth } },
    ];
    // --8<-- [end:routes]
</script>

{#if appError.current}
    <ErrorDisplay error={appError.current.error} title={appError.current.title} />
{:else}
    <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
        <Header/>
        <Toaster richColors position="top-right" />
        <main class="flex-grow">
            {#if !authInitialized}
                <div class="flex items-center justify-center min-h-[50vh]">
                    <Spinner size="large" />
                </div>
            {:else}
                <Router base="/" {routes} />
            {/if}
        </main>
        <Footer/>
    </div>
{/if}
