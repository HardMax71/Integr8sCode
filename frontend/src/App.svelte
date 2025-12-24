<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Router, type Route, goto } from "@mateothegreat/svelte5-router";
    import Header from "./components/Header.svelte";
    import Footer from "./components/Footer.svelte";
    import ToastContainer from "./components/ToastContainer.svelte";
    import Spinner from "./components/Spinner.svelte";
    import ErrorDisplay from "./components/ErrorDisplay.svelte";
    import { theme } from './stores/theme';
    import { initializeAuth, AuthInitializer } from './lib/auth-init';
    import { appError } from './stores/errorStore';
    import { isAuthenticated } from './stores/auth';
    import { get } from 'svelte/store';

    // Page components
    import Home from "./routes/Home.svelte";
    import Login from "./routes/Login.svelte";
    import Register from "./routes/Register.svelte";
    import Privacy from "./routes/Privacy.svelte";
    import Editor from "./routes/Editor.svelte";
    import Settings from "./routes/Settings.svelte";
    import Notifications from "./routes/Notifications.svelte";
    import AdminEvents from "./routes/admin/AdminEvents.svelte";
    import AdminSagas from "./routes/admin/AdminSagas.svelte";
    import AdminUsers from "./routes/admin/AdminUsers.svelte";
    import AdminSettings from "./routes/admin/AdminSettings.svelte";

    // Theme value derived from store with proper cleanup
    let themeValue = $state('auto');
    const unsubscribeTheme = theme.subscribe(value => { themeValue = value; });

    // Global error state
    let globalError = $state<{ error: Error | string; title?: string } | null>(null);
    const unsubscribeError = appError.subscribe(value => { globalError = value; });

    onDestroy(() => {
        unsubscribeTheme();
        unsubscribeError();
    });

    let authInitialized = $state(false);

    // Initialize auth before rendering routes
    onMount(async () => {
        try {
            await initializeAuth();
            console.log('[App] Authentication initialized');
        } catch (err) {
            console.error('[App] Auth initialization failed:', err);
        } finally {
            authInitialized = true;
        }
    });

    // Auth hook for protected routes
    const requireAuth = async () => {
        await AuthInitializer.waitForInit();
        if (!get(isAuthenticated)) {
            const currentPath = window.location.pathname + window.location.search;
            if (currentPath !== '/login' && currentPath !== '/register') {
                sessionStorage.setItem('redirectAfterLogin', currentPath);
            }
            goto('/login');
            return false;
        }
        return true;
    };

    // Routes configuration
    const routes: Route[] = [
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
        { path: "/admin/sagas", component: AdminSagas, hooks: { pre: requireAuth } },
        { path: "/admin/users", component: AdminUsers, hooks: { pre: requireAuth } },
        { path: "/admin/settings", component: AdminSettings, hooks: { pre: requireAuth } },
        { path: "^/admin$", component: AdminEvents, hooks: { pre: requireAuth } },
    ];
</script>

{#if globalError}
    <ErrorDisplay error={globalError.error} title={globalError.title} />
{:else}
    <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
        <Header/>
        <ToastContainer/>
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
