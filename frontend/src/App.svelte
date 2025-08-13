<script>
    import { onMount } from 'svelte';
    import { Route, Router } from "svelte-routing";
    import Home from "./routes/Home.svelte";
    import Login from "./routes/Login.svelte";
    import Register from "./routes/Register.svelte";
    import Editor from "./routes/Editor.svelte";
    import AdminEvents from "./routes/admin/AdminEvents.svelte";
    import AdminProjections from "./routes/admin/AdminProjections.svelte";
    import AdminStats from "./routes/admin/AdminStats.svelte";
    import AdminUsers from "./routes/admin/AdminUsers.svelte";
    import AdminSettings from "./routes/admin/AdminSettings.svelte";
    import KafkaMetrics from "./routes/admin/KafkaMetrics.svelte";
    import AdminSagas from "./routes/admin/AdminSagas.svelte";
    import Settings from "./routes/Settings.svelte";
    import NotificationsPage from "./routes/Notifications.svelte";
    import Header from "./components/Header.svelte";
    import Footer from "./components/Footer.svelte";
    import Notifications from "./components/Notifications.svelte";
    import ProtectedRoute from "./components/ProtectedRoute.svelte";
    import Spinner from "./components/Spinner.svelte";
    import { theme } from './stores/theme.js';
    import { initializeAuth } from './lib/auth-init.js';

    $: themeValue = $theme;

    export let url = "";
    
    let authInitialized = false;
    
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
</script>

{#if !authInitialized}
    <div class="flex items-center justify-center min-h-screen bg-bg-default dark:bg-dark-bg-default">
        <Spinner size="large" />
    </div>
{:else}
    <Router {url}>
        <!-- Admin routes with standard layout -->
        <Route path="/admin/events">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminEvents/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin/projections">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminProjections/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin/sagas">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminSagas/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin/stats">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminStats/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin/users">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminUsers/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin/settings">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminSettings/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin/kafka">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <KafkaMetrics/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/admin">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow">
                            <AdminEvents/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
    <!-- Regular app routes with layout -->
    <Route path="/">
        <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
            <Header/>
            <div class="flex-grow flex flex-col">
                <Notifications/>
                <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                    <Home/>
                </main>
            </div>
            <Footer/>
        </div>
    </Route>
    
        <Route path="/editor">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                            <Editor/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
    <Route path="/login">
        <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
            <Header/>
            <div class="flex-grow flex flex-col">
                <Notifications/>
                <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                    <Login/>
                </main>
            </div>
            <Footer/>
        </div>
    </Route>
    
    <Route path="/register">
        <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
            <Header/>
            <div class="flex-grow flex flex-col">
                <Notifications/>
                <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                    <Register/>
                </main>
            </div>
            <Footer/>
        </div>
    </Route>
    
        <Route path="/settings">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                            <Settings/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    
        <Route path="/notifications">
            <ProtectedRoute>
                <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
                    <Header/>
                    <div class="flex-grow flex flex-col">
                        <Notifications/>
                        <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                            <NotificationsPage/>
                        </main>
                    </div>
                    <Footer/>
                </div>
            </ProtectedRoute>
        </Route>
    </Router>
{/if}

<style>
    /* Styles moved to Tailwind classes */
</style>