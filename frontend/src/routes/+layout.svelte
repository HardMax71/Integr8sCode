<script lang="ts">
    import '../app.css';
    import { setTheme } from '#stores/theme.svelte.ts';
    import { onMount, type Snippet } from 'svelte';
    import { Toaster } from 'svelte-sonner';
    import { Tooltip } from 'bits-ui';
    import { ModeWatcher } from 'mode-watcher';
    import { QueryClientProvider, createQuery } from '@tanstack/svelte-query';
    import { getUserSettingsApiV1UserSettingsGetOptions } from '#lib/api/index.ts';
    import Header from '#components/Header.svelte';
    import Footer from '#components/Footer.svelte';
    import Spinner from '#components/Spinner.svelte';
    import { authStore } from '#stores/auth.svelte.ts';
    import { logger } from '#lib/logger.ts';
    import { queryClient } from '#lib/query-client.ts';

    let { children }: { children: Snippet } = $props();

    const log = logger.withTag('App');

    let authInitialized = $state(false);

    // This component provides the client, so it can't read it from context yet
    const settings = createQuery(
        () => ({
            ...getUserSettingsApiV1UserSettingsGetOptions(),
            enabled: authStore.session.status === 'signed-in',
        }),
        () => queryClient,
    );

    $effect(() => {
        if (settings.data) setTheme(settings.data.theme);
    });

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
</script>

<!-- The CSP would block its inline head script and its transition-blocking style tag; with no SSR the script would run no earlier anyway -->
<ModeWatcher modeStorageKey="app-theme" disableHeadScriptInjection disableTransitions={false} />
<QueryClientProvider client={queryClient}>
    <Tooltip.Provider delayDuration={300}>
        <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default pt-16">
            <Header />
            <Toaster richColors position="top-right" />
            <main class="flex-grow">
                {#if !authInitialized}
                    <div class="flex items-center justify-center min-h-[50vh]">
                        <Spinner size="large" />
                    </div>
                {:else}
                    {@render children()}
                {/if}
            </main>
            <Footer />
        </div>
    </Tooltip.Provider>
</QueryClientProvider>
