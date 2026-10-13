<script lang="ts">
    import '../app.css';
    import { untrack } from 'svelte';
    import { Toaster } from 'svelte-sonner';
    import { Tooltip } from 'bits-ui';
    import { ModeWatcher, setMode } from 'mode-watcher';
    import { QueryClientProvider, createQuery } from '@tanstack/svelte-query';
    import { getUserSettingsApiV1UserSettingsGetOptions } from '#lib/api/index.ts';
    import Header from '#components/Header.svelte';
    import Footer from '#components/Footer.svelte';
    import { queryClient } from '#lib/query-client.ts';
    import type { LayoutProps } from './$types';

    let { data, children }: LayoutProps = $props();

    // This component provides the client, so it can't read it from context yet
    const settings = createQuery(
        () => ({
            ...getUserSettingsApiV1UserSettingsGetOptions(),
            enabled: data.user !== null,
        }),
        () => queryClient,
    );

    $effect(() => {
        if (!settings.data) return;
        const { theme } = settings.data;
        // setMode reads mode-watcher's own state, so tracking it would undo every later toggle
        untrack(() => {
            setMode(theme);
        });
    });
</script>

<!-- The CSP would block its inline head script and its transition-blocking style tag; with no SSR the script would run no earlier anyway -->
<ModeWatcher modeStorageKey="app-theme" disableHeadScriptInjection disableTransitions={false} />
<QueryClientProvider client={queryClient}>
    <Tooltip.Provider delayDuration={300}>
        <div class="flex flex-col min-h-screen bg-page pt-16">
            <Header />
            <Toaster richColors position="top-right" />
            <main class="flex-grow">
                {@render children()}
            </main>
            <Footer />
        </div>
    </Tooltip.Provider>
</QueryClientProvider>
