<script lang="ts">
    import type { Snippet } from 'svelte';
    import { onMount, onDestroy } from 'svelte';
    import { Router, type Route } from "@mateothegreat/svelte5-router";
    import Home from "./routes/Home.svelte";
    import Login from "./routes/Login.svelte";
    import Register from "./routes/Register.svelte";
    import Editor from "./routes/Editor.svelte";
    import AdminEvents from "./routes/admin/AdminEvents.svelte";
    import AdminUsers from "./routes/admin/AdminUsers.svelte";
    import AdminSettings from "./routes/admin/AdminSettings.svelte";
    import AdminSagas from "./routes/admin/AdminSagas.svelte";
    import Settings from "./routes/Settings.svelte";
    import NotificationsPage from "./routes/Notifications.svelte";
    import Privacy from "./routes/Privacy.svelte";
    import Header from "./components/Header.svelte";
    import Footer from "./components/Footer.svelte";
    import ToastContainer from "./components/ToastContainer.svelte";
    import ProtectedRoute from "./components/ProtectedRoute.svelte";
    import Spinner from "./components/Spinner.svelte";
    import { theme } from './stores/theme';
    import { initializeAuth } from './lib/auth-init';

    // Theme value derived from store with proper cleanup
    let themeValue = $state('auto');
    const unsubscribeTheme = theme.subscribe(value => { themeValue = value; });

    onDestroy(() => {
        unsubscribeTheme();
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

    // Routes for public pages (no auth required)
    const publicRoutes: Route[] = [
        { path: "/", component: homeSnippet },
        { path: "/login", component: loginSnippet },
        { path: "/register", component: registerSnippet },
        { path: "/privacy", component: privacySnippet },
    ];

    // Routes for protected pages (auth required)
    const protectedRoutes: Route[] = [
        { path: "/editor", component: editorSnippet },
        { path: "/settings", component: settingsSnippet },
        { path: "/notifications", component: notificationsSnippet },
        { path: "/admin/events", component: adminEventsSnippet },
        { path: "/admin/sagas", component: adminSagasSnippet },
        { path: "/admin/users", component: adminUsersSnippet },
        { path: "/admin/settings", component: adminSettingsSnippet },
        { path: "/admin", component: adminEventsSnippet },
    ];

    const allRoutes: Route[] = [...publicRoutes, ...protectedRoutes];
</script>

<!-- Layout wrapper snippet -->
{#snippet layoutWrapper(content: Snippet, isProtected: boolean = false, isFullWidth: boolean = false)}
    {#if isProtected}
        <ProtectedRoute>
            <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                <Header/>
                <div class="flex-grow flex flex-col">
                    <ToastContainer/>
                    <main class={isFullWidth ? "flex-grow" : "flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8"}>
                        {@render content()}
                    </main>
                </div>
                <Footer/>
            </div>
        </ProtectedRoute>
    {:else}
        <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
            <Header/>
            <div class="flex-grow flex flex-col">
                <ToastContainer/>
                <main class={isFullWidth ? "flex-grow" : "flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8"}>
                    {@render content()}
                </main>
            </div>
            <Footer/>
        </div>
    {/if}
{/snippet}

<!-- Public route snippets -->
{#snippet homeSnippet()}
    {@render layoutWrapper(homeContent, false)}
{/snippet}

{#snippet homeContent()}
    <Home/>
{/snippet}

{#snippet loginSnippet()}
    {@render layoutWrapper(loginContent, false)}
{/snippet}

{#snippet loginContent()}
    <Login/>
{/snippet}

{#snippet registerSnippet()}
    {@render layoutWrapper(registerContent, false)}
{/snippet}

{#snippet registerContent()}
    <Register/>
{/snippet}

{#snippet privacySnippet()}
    {@render layoutWrapper(privacyContent, false)}
{/snippet}

{#snippet privacyContent()}
    <Privacy/>
{/snippet}

<!-- Protected route snippets -->
{#snippet editorSnippet()}
    {@render layoutWrapper(editorContent, true)}
{/snippet}

{#snippet editorContent()}
    <Editor/>
{/snippet}

{#snippet settingsSnippet()}
    {@render layoutWrapper(settingsContent, true)}
{/snippet}

{#snippet settingsContent()}
    <Settings/>
{/snippet}

{#snippet notificationsSnippet()}
    {@render layoutWrapper(notificationsContent, true)}
{/snippet}

{#snippet notificationsContent()}
    <NotificationsPage/>
{/snippet}

<!-- Admin route snippets (full width) -->
{#snippet adminEventsSnippet()}
    {@render layoutWrapper(adminEventsContent, true, true)}
{/snippet}

{#snippet adminEventsContent()}
    <AdminEvents/>
{/snippet}

{#snippet adminSagasSnippet()}
    {@render layoutWrapper(adminSagasContent, true, true)}
{/snippet}

{#snippet adminSagasContent()}
    <AdminSagas/>
{/snippet}

{#snippet adminUsersSnippet()}
    {@render layoutWrapper(adminUsersContent, true, true)}
{/snippet}

{#snippet adminUsersContent()}
    <AdminUsers/>
{/snippet}

{#snippet adminSettingsSnippet()}
    {@render layoutWrapper(adminSettingsContent, true, true)}
{/snippet}

{#snippet adminSettingsContent()}
    <AdminSettings/>
{/snippet}

{#if !authInitialized}
    <div class="flex items-center justify-center min-h-screen bg-bg-default dark:bg-dark-bg-default">
        <Spinner size="large" />
    </div>
{:else}
    <Router base="/" routes={allRoutes} />
{/if}

<style>
    /* Styles moved to Tailwind classes */
</style>
