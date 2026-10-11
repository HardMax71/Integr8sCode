<script lang="ts">
    import '../app.css';
    import '#stores/theme.svelte.ts';
    import { onMount, type Snippet } from 'svelte';
    import { Toaster } from 'svelte-sonner';
    import { QueryClientProvider } from '@tanstack/svelte-query';
    import Header from '#components/Header.svelte';
    import Footer from '#components/Footer.svelte';
    import Spinner from '#components/Spinner.svelte';
    import { authStore } from '#stores/auth.svelte.ts';
    import { logger } from '#lib/logger.ts';
    import { queryClient } from '#lib/query-client.ts';

    let { children }: { children: Snippet } = $props();

    const log = logger.withTag('App');

    let authInitialized = $state(false);

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

<QueryClientProvider client={queryClient}>
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
</QueryClientProvider>
